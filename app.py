"""Streamlit app for testing AWS GameLift FlexMatch matchmaking.

Generic and reusable: no game-specific logic, no hardcoded configuration.
"""

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
import streamlit as st
from botocore.exceptions import BotoCoreError, ClientError


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

STATUS_COLORS = {
    "QUEUED": "#9e9e9e",
    "SEARCHING": "#2196f3",
    "PLACING": "#ffc107",
    "COMPLETED": "#4caf50",
    "FAILED": "#f44336",
    "TIMED_OUT": "#ff9800",
    "CANCELLED": "#9e9e9e",
}

TERMINAL_STATUSES = {"COMPLETED", "FAILED", "TIMED_OUT", "CANCELLED"}

ATTRIBUTE_TYPE_TO_AWS = {
    "number": "N",
    "string": "S",
    "string_list": "SL",
    "string_number_map": "SDM",
}


# --------------------------------------------------------------------------- #
# Session state init
# --------------------------------------------------------------------------- #

def init_session_state() -> None:
    defaults = {
        "aws_config": {"profile": "", "region": "eu-west-1", "config_name": ""},
        "ruleset": None,
        "matchmaking_config": None,
        "active_tickets": [],
        "ticket_drafts": [],
        "ticket_details": {},
        "load_status": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# --------------------------------------------------------------------------- #
# AWS helpers
# --------------------------------------------------------------------------- #

def get_gamelift_client(profile: str, region: str):
    session = boto3.Session(profile_name=profile or None, region_name=region or None)
    return session.client("gamelift")


def load_configuration(profile: str, region: str, config_name: str) -> tuple[dict, dict]:
    client = get_gamelift_client(profile, region)

    config_response = client.describe_matchmaking_configurations(Names=[config_name])
    configs = config_response.get("Configurations", [])
    if not configs:
        raise ValueError(f"Matchmaking configuration '{config_name}' not found")
    config = configs[0]

    rule_set_name = config.get("RuleSetName")
    if not rule_set_name:
        raise ValueError("Configuration has no RuleSetName")

    rule_set_response = client.describe_matchmaking_rule_sets(Names=[rule_set_name])
    rule_sets = rule_set_response.get("RuleSets", [])
    if not rule_sets:
        raise ValueError(f"Rule set '{rule_set_name}' not found")

    rule_set_body = rule_sets[0].get("RuleSetBody", "{}")
    ruleset = json.loads(rule_set_body)
    return config, ruleset


def describe_tickets(profile: str, region: str, ticket_ids: list[str]) -> list[dict]:
    """Describe tickets in chunks of 10 (AWS limit)."""
    if not ticket_ids:
        return []
    client = get_gamelift_client(profile, region)
    results: list[dict] = []
    for i in range(0, len(ticket_ids), 10):
        chunk = ticket_ids[i : i + 10]
        response = client.describe_matchmaking(TicketIds=chunk)
        results.extend(response.get("TicketList", []))
    return results


def stop_ticket(profile: str, region: str, ticket_id: str) -> None:
    client = get_gamelift_client(profile, region)
    client.stop_matchmaking(TicketId=ticket_id)


def start_ticket(
    profile: str,
    region: str,
    config_name: str,
    players: list[dict],
) -> str:
    client = get_gamelift_client(profile, region)
    response = client.start_matchmaking(
        ConfigurationName=config_name,
        Players=players,
    )
    return response["MatchmakingTicket"]["TicketId"]


# --------------------------------------------------------------------------- #
# Ruleset helpers
# --------------------------------------------------------------------------- #

def get_player_attributes(ruleset: dict) -> list[dict]:
    return ruleset.get("playerAttributes", []) or []


def build_player_attribute_payload(
    attr_def: dict, raw_value: Any
) -> dict | None:
    """Convert a form value into the AWS PlayerAttributes payload entry.

    boto3 expects each attribute as {"N": ...} / {"S": ...} / {"SL": ...} / {"SDM": ...}.
    Empty string / list / map values are omitted because boto3 rejects them
    client-side (min length 1); numbers are always sent (0.0 is valid).
    """
    attr_type = attr_def.get("type", "")

    if attr_type == "number":
        if raw_value is None or raw_value == "":
            return {"N": 0.0}
        return {"N": float(raw_value)}
    if attr_type == "string":
        text = "" if raw_value is None else str(raw_value)
        if not text:
            return None
        return {"S": text}
    if attr_type == "string_list":
        if not raw_value:
            return None
        items = [item.strip() for item in str(raw_value).split(",") if item.strip()]
        if not items:
            return None
        return {"SL": items}
    if attr_type == "string_number_map":
        text = str(raw_value or "").strip()
        if not text:
            return None
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("string_number_map must be a JSON object")
        if not parsed:
            return None
        return {"SDM": {str(k): float(v) for k, v in parsed.items()}}
    return None


# --------------------------------------------------------------------------- #
# UI components
# --------------------------------------------------------------------------- #

def render_sidebar() -> None:
    st.sidebar.header("AWS Configuration")

    aws_config = st.session_state["aws_config"]
    profile = st.sidebar.text_input("AWS Profile Name", value=aws_config["profile"])
    region = st.sidebar.text_input("AWS Region", value=aws_config["region"] or "eu-west-1")
    config_name = st.sidebar.text_input(
        "Matchmaking Configuration Name", value=aws_config["config_name"]
    )

    st.session_state["aws_config"] = {
        "profile": profile.strip(),
        "region": region.strip(),
        "config_name": config_name.strip(),
    }

    if st.sidebar.button("Load Configuration", use_container_width=True):
        if not config_name.strip():
            st.session_state["load_status"] = ("error", "Configuration name is required")
        else:
            try:
                config, ruleset = load_configuration(
                    profile.strip(), region.strip(), config_name.strip()
                )
                st.session_state["matchmaking_config"] = config
                st.session_state["ruleset"] = ruleset
                st.session_state["load_status"] = (
                    "success",
                    f"Loaded '{config_name}' (rule set: {config.get('RuleSetName')})",
                )
            except (ClientError, BotoCoreError, ValueError, json.JSONDecodeError) as exc:
                st.session_state["matchmaking_config"] = None
                st.session_state["ruleset"] = None
                st.session_state["load_status"] = ("error", str(exc))

    status = st.session_state.get("load_status")
    if status is not None:
        kind, message = status
        if kind == "success":
            st.sidebar.success(message)
        else:
            st.sidebar.error(message)


def render_ruleset_inspector() -> None:
    st.header("Ruleset Inspector")
    ruleset = st.session_state.get("ruleset")
    if not ruleset:
        st.info("Load a configuration from the sidebar to inspect its ruleset.")
        return

    # Algorithm
    st.subheader("Algorithm")
    algorithm = ruleset.get("algorithm", {}) or {}
    algo_rows = [
        {"Field": "strategy", "Value": algorithm.get("strategy", "")},
        {"Field": "expansionAgeSelection", "Value": algorithm.get("expansionAgeSelection", "")},
        {"Field": "batchingPreference", "Value": algorithm.get("batchingPreference", "")},
    ]
    st.table(algo_rows)

    # Teams
    st.subheader("Teams")
    teams = ruleset.get("teams", []) or []
    if teams:
        st.table(
            [
                {
                    "name": team.get("name", ""),
                    "minPlayers": team.get("minPlayers", ""),
                    "maxPlayers": team.get("maxPlayers", ""),
                }
                for team in teams
            ]
        )
    else:
        st.caption("No teams defined.")

    # Player attributes
    st.subheader("Player Attributes")
    attributes = get_player_attributes(ruleset)
    if attributes:
        st.table(
            [
                {
                    "name": attr.get("name", ""),
                    "type": attr.get("type", ""),
                    "default": _format_default(attr.get("default")),
                }
                for attr in attributes
            ]
        )
    else:
        st.caption("No player attributes defined.")

    # Rules
    st.subheader("Rules")
    rules = ruleset.get("rules", []) or []
    if rules:
        st.table([_summarize_rule(rule) for rule in rules])
    else:
        st.caption("No rules defined.")

    # Expansions
    st.subheader("Expansions")
    expansions = ruleset.get("expansions", []) or []
    if expansions:
        expansion_rows = []
        for expansion in expansions:
            steps = expansion.get("steps", []) or []
            steps_str = ", ".join(
                f"{step.get('waitTimeSeconds', '?')}s -> {step.get('value', '')}"
                for step in steps
            )
            expansion_rows.append(
                {"target": expansion.get("target", ""), "steps": steps_str}
            )
        st.table(expansion_rows)
    else:
        st.caption("No expansions defined.")


def _format_default(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def _summarize_rule(rule: dict) -> dict:
    rule_type = rule.get("type", "")
    summary = {
        "name": rule.get("name", ""),
        "type": rule_type,
        "description": rule.get("description", ""),
    }

    if rule_type == "batchDistance":
        properties = (
            f"batchAttribute={rule.get('batchAttribute', '')}, "
            f"maxDistance={rule.get('maxDistance', '')}, "
            f"partyAggregation={rule.get('partyAggregation', '')}"
        )
    elif rule_type == "comparison":
        properties = (
            f"measurements={rule.get('measurements', [])}, "
            f"operation={rule.get('operation', '')}, "
            f"referenceValue={rule.get('referenceValue', '')}"
        )
    elif rule_type == "distance":
        properties = (
            f"measurements={rule.get('measurements', [])}, "
            f"referenceValue={rule.get('referenceValue', '')}, "
            f"maxDistance={rule.get('maxDistance', '')}"
        )
    elif rule_type == "collection":
        extras = []
        if "minCount" in rule:
            extras.append(f"minCount={rule.get('minCount')}")
        if "maxCount" in rule:
            extras.append(f"maxCount={rule.get('maxCount')}")
        properties = (
            f"measurements={rule.get('measurements', [])}, "
            f"operation={rule.get('operation', '')}"
        )
        if extras:
            properties += ", " + ", ".join(extras)
    elif rule_type == "latency":
        properties = f"maxLatency={rule.get('maxLatency', '')}"
    elif rule_type == "compound":
        properties = f"statement={rule.get('statement', '')}"
    else:
        properties = ""

    summary["properties"] = properties
    return summary


def render_start_tickets() -> None:
    st.header("Start Tickets")
    ruleset = st.session_state.get("ruleset")
    aws_config = st.session_state["aws_config"]

    if not ruleset:
        st.warning("Load a configuration first")
        return

    attribute_defs = get_player_attributes(ruleset)
    _ensure_ticket_drafts(ruleset)
    ticket_drafts: list[dict] = st.session_state["ticket_drafts"]

    st.caption(
        "Each ticket is one matchmaking request. Multiple players inside the same "
        "ticket are treated as a party by FlexMatch."
    )

    bulk_col1, bulk_col2, bulk_col3 = st.columns([2, 2, 2])
    bulk_count = bulk_col1.number_input(
        "Bulk quantity",
        min_value=1,
        max_value=200,
        value=1,
        step=1,
        key="bulk_count",
    )
    if bulk_col2.button("Add N solo tickets", help="One player per ticket, default values"):
        for _ in range(int(bulk_count)):
            ticket_drafts.append(_new_ticket_draft(ruleset, players=1))
        st.rerun()
    if bulk_col3.button("Reset drafts"):
        ticket_drafts.clear()
        ticket_drafts.append(_new_ticket_draft(ruleset, players=1))
        st.rerun()

    st.divider()

    to_remove_tickets: list[int] = []
    for ticket_idx, ticket in enumerate(ticket_drafts):
        with st.container(border=True):
            header_col1, header_col2 = st.columns([5, 1])
            header_col1.markdown(
                f"### Ticket {ticket_idx + 1} — {len(ticket['players'])} player(s)"
            )
            if header_col2.button(
                "Remove ticket", key=f"rm_ticket_{ticket['_uid']}"
            ):
                to_remove_tickets.append(ticket_idx)

            _render_ticket_players(ticket, attribute_defs)

            if st.button("Add player to this ticket", key=f"add_player_{ticket['_uid']}"):
                ticket["players"].append(_new_player_draft(ruleset))
                st.rerun()

    if to_remove_tickets:
        for idx in sorted(to_remove_tickets, reverse=True):
            ticket_drafts.pop(idx)
        if not ticket_drafts:
            ticket_drafts.append(_new_ticket_draft(ruleset, players=1))
        st.rerun()

    if st.button("Add empty ticket"):
        ticket_drafts.append(_new_ticket_draft(ruleset, players=1))
        st.rerun()

    st.divider()

    if st.button("Start Matchmaking", type="primary"):
        _start_matchmaking_batch(ticket_drafts, attribute_defs, aws_config)

    active_tickets = st.session_state.get("active_tickets", [])
    if active_tickets:
        st.subheader("Recently created tickets")
        for ticket_id in active_tickets:
            st.code(ticket_id, language=None)


def _ensure_ticket_drafts(ruleset: dict) -> None:
    if not st.session_state.get("ticket_drafts"):
        st.session_state["ticket_drafts"] = [_new_ticket_draft(ruleset, players=1)]


def _new_ticket_draft(ruleset: dict, players: int = 1) -> dict:
    return {
        "_uid": uuid.uuid4().hex,
        "players": [_new_player_draft(ruleset) for _ in range(max(1, players))],
    }


def _new_player_draft(ruleset: dict) -> dict:
    attributes: dict[str, Any] = {}
    for attr_def in get_player_attributes(ruleset):
        attributes[attr_def.get("name", "")] = _form_default_for_attribute(attr_def)
    return {
        "_uid": uuid.uuid4().hex,
        "player_id": "",
        "attributes": attributes,
        "latency": [],
    }


def _form_default_for_attribute(attr_def: dict) -> Any:
    attr_type = attr_def.get("type", "")
    default = attr_def.get("default")
    if attr_type == "number":
        return float(default) if default is not None else 0.0
    if attr_type == "string":
        return str(default) if default is not None else ""
    if attr_type == "string_list":
        if isinstance(default, list):
            return ", ".join(str(x) for x in default)
        return ""
    if attr_type == "string_number_map":
        if isinstance(default, dict):
            return json.dumps(default, indent=2)
        return "{}"
    return ""


def _render_ticket_players(ticket: dict, attribute_defs: list[dict]) -> None:
    to_remove: list[int] = []
    for player_idx, player in enumerate(ticket["players"]):
        with st.container(border=True):
            head_col1, head_col2, head_col3 = st.columns([2, 3, 1])
            head_col1.markdown(f"**Player {player_idx + 1}**")
            player["player_id"] = head_col2.text_input(
                "Player ID (blank = auto)",
                value=player.get("player_id", ""),
                key=f"pid_{ticket['_uid']}_{player['_uid']}",
                label_visibility="collapsed",
                placeholder="Player ID (blank = auto-generated)",
            )
            remove_disabled = len(ticket["players"]) <= 1
            if head_col3.button(
                "Remove",
                key=f"rm_player_{ticket['_uid']}_{player['_uid']}",
                disabled=remove_disabled,
            ):
                to_remove.append(player_idx)

            _render_player_attributes_form(ticket, player, attribute_defs)
            _render_player_latency(ticket, player)

    if to_remove:
        for idx in sorted(to_remove, reverse=True):
            ticket["players"].pop(idx)
        st.rerun()


def _render_player_attributes_form(
    ticket: dict, player: dict, attribute_defs: list[dict]
) -> None:
    if not attribute_defs:
        st.caption("No player attributes declared in the ruleset.")
        return

    st.caption("Attributes")
    for attr_def in attribute_defs:
        name = attr_def.get("name", "")
        attr_type = attr_def.get("type", "")
        key = f"attr_{ticket['_uid']}_{player['_uid']}_{name}"
        current = player["attributes"].get(name, _form_default_for_attribute(attr_def))
        label = _attribute_label(attr_def)

        if attr_type == "number":
            player["attributes"][name] = st.number_input(
                label, value=float(current), key=key, format="%.4f"
            )
        elif attr_type == "string":
            player["attributes"][name] = st.text_input(label, value=str(current), key=key)
        elif attr_type == "string_list":
            player["attributes"][name] = st.text_input(
                f"{label} — comma-separated", value=str(current), key=key
            )
        elif attr_type == "string_number_map":
            player["attributes"][name] = st.text_area(
                f"{label} — JSON object", value=str(current), key=key, height=100
            )
        else:
            st.caption(f"Unsupported attribute type: {attr_type} ({name})")


def _attribute_label(attr_def: dict) -> str:
    name = attr_def.get("name", "")
    attr_type = attr_def.get("type", "")
    default = attr_def.get("default")
    if default is None:
        return f"{name} ({attr_type}) — required"
    if isinstance(default, (dict, list)):
        return f"{name} ({attr_type}) — default: {json.dumps(default)}"
    return f"{name} ({attr_type}) — default: {default}"


def _render_player_latency(ticket: dict, player: dict) -> None:
    st.caption("Latency")
    rows: list[dict] = player["latency"]
    to_remove: list[int] = []
    for row in rows:
        if "_uid" not in row:
            row["_uid"] = uuid.uuid4().hex

    for row_idx, row in enumerate(rows):
        col_region, col_ms, col_del = st.columns([3, 2, 1])
        row["region"] = col_region.text_input(
            "Region",
            value=row.get("region", ""),
            key=f"lat_r_{ticket['_uid']}_{player['_uid']}_{row['_uid']}",
            label_visibility="collapsed",
            placeholder="eu-west-1",
        )
        row["ms"] = col_ms.number_input(
            "ms",
            value=int(row.get("ms", 50)),
            min_value=0,
            max_value=5000,
            step=1,
            key=f"lat_ms_{ticket['_uid']}_{player['_uid']}_{row['_uid']}",
            label_visibility="collapsed",
        )
        if col_del.button(
            "Remove",
            key=f"lat_del_{ticket['_uid']}_{player['_uid']}_{row['_uid']}",
        ):
            to_remove.append(row_idx)

    if to_remove:
        for idx in sorted(to_remove, reverse=True):
            rows.pop(idx)
        st.rerun()

    if st.button(
        "Add latency row",
        key=f"lat_add_{ticket['_uid']}_{player['_uid']}",
    ):
        rows.append({"_uid": uuid.uuid4().hex, "region": "", "ms": 50})
        st.rerun()


def _start_matchmaking_batch(
    ticket_drafts: list[dict],
    attribute_defs: list[dict],
    aws_config: dict,
) -> None:
    profile = aws_config["profile"]
    region = aws_config["region"]
    config_name = aws_config["config_name"]

    if not config_name:
        st.error("Configuration name is required")
        return
    if not ticket_drafts:
        st.error("No tickets to start")
        return

    missing = _find_missing_required_attributes(ticket_drafts, attribute_defs)
    if missing:
        st.error(
            "Fill all required attributes before starting:\n"
            + "\n".join(f"- {m}" for m in missing)
        )
        return

    created: list[str] = []
    failed: list[str] = []

    progress = st.progress(0.0, text="Starting tickets...")
    total = len(ticket_drafts)
    for t_idx, ticket in enumerate(ticket_drafts):
        try:
            players_payload = _build_ticket_players_payload(
                ticket, attribute_defs, t_idx
            )
        except (ValueError, json.JSONDecodeError) as exc:
            failed.append(f"Ticket {t_idx + 1}: invalid attribute value: {exc}")
            progress.progress((t_idx + 1) / total)
            continue

        try:
            ticket_id = start_ticket(profile, region, config_name, players_payload)
            created.append(ticket_id)
        except (ClientError, BotoCoreError) as exc:
            failed.append(f"Ticket {t_idx + 1}: {exc}")

        progress.progress((t_idx + 1) / total, text=f"Started {t_idx + 1}/{total}")

    progress.empty()
    if created:
        st.session_state["active_tickets"].extend(created)
        st.success(f"Created {len(created)} ticket(s)")
    if failed:
        st.error("Failed to start some tickets:\n" + "\n".join(failed))


def _find_missing_required_attributes(
    ticket_drafts: list[dict], attribute_defs: list[dict]
) -> list[str]:
    """Return messages for required attributes (no default in ruleset) left empty."""
    required = [a for a in attribute_defs if a.get("default") is None]
    if not required:
        return []

    messages: list[str] = []
    for t_idx, ticket in enumerate(ticket_drafts):
        for p_idx, player in enumerate(ticket["players"]):
            for attr_def in required:
                name = attr_def.get("name", "")
                value = player["attributes"].get(name)
                if build_player_attribute_payload(attr_def, value) is None:
                    messages.append(
                        f"Ticket {t_idx + 1}, Player {p_idx + 1}: '{name}' is required"
                    )
    return messages


def _build_ticket_players_payload(
    ticket: dict, attribute_defs: list[dict], ticket_idx: int
) -> list[dict]:
    payload: list[dict] = []
    for p_idx, player in enumerate(ticket["players"]):
        player_id = (player.get("player_id") or "").strip()
        if not player_id:
            player_id = (
                f"test-player-{ticket_idx + 1}-{p_idx + 1}-{uuid.uuid4().hex[:8]}"
            )

        attributes_payload: dict[str, dict] = {}
        for attr_def in attribute_defs:
            name = attr_def.get("name", "")
            raw_value = player["attributes"].get(name)
            entry = build_player_attribute_payload(attr_def, raw_value)
            if entry is not None:
                attributes_payload[name] = entry

        latency_map: dict[str, int] = {}
        for row in player["latency"]:
            region_name = (row.get("region") or "").strip()
            if region_name:
                latency_map[region_name] = int(row.get("ms", 0))

        player_entry: dict[str, Any] = {
            "PlayerId": player_id,
            "PlayerAttributes": attributes_payload,
        }
        if latency_map:
            player_entry["LatencyInMs"] = latency_map
        payload.append(player_entry)
    return payload


def render_monitor_tickets() -> None:
    st.header("Monitor Tickets")
    aws_config = st.session_state["aws_config"]

    top_col1, top_col2, top_col3 = st.columns([2, 2, 2])
    auto_refresh = top_col1.checkbox("Auto-refresh", value=False, key="auto_refresh")
    refresh_interval = top_col2.number_input(
        "Interval (s)", min_value=2, max_value=300, value=10, step=1, key="refresh_interval"
    )
    refresh_now = top_col3.button("Refresh Now")

    add_col1, add_col2 = st.columns([4, 1])
    manual_ticket = add_col1.text_input(
        "Add existing ticket ID", key="manual_ticket_input", placeholder="ticket-id..."
    )
    if add_col2.button("Add"):
        ticket_id = manual_ticket.strip()
        if ticket_id and ticket_id not in st.session_state["active_tickets"]:
            st.session_state["active_tickets"].append(ticket_id)
            st.rerun()

    action_col1, action_col2 = st.columns(2)
    if action_col1.button("Stop All Tickets"):
        _stop_all_active_tickets(aws_config)
    if action_col2.button("Clear Terminal Tickets"):
        _clear_terminal_tickets()

    ticket_ids = list(st.session_state["active_tickets"])
    if not ticket_ids:
        st.info("No tickets to monitor. Start tickets in the previous tab or add an ID above.")
        return

    if refresh_now or auto_refresh or not st.session_state["ticket_details"]:
        try:
            tickets = describe_tickets(
                aws_config["profile"], aws_config["region"], ticket_ids
            )
            st.session_state["ticket_details"] = {
                ticket["TicketId"]: ticket for ticket in tickets
            }
        except (ClientError, BotoCoreError) as exc:
            st.error(f"Failed to describe tickets: {exc}")

    for ticket_id in ticket_ids:
        ticket = st.session_state["ticket_details"].get(ticket_id)
        _render_ticket_card(ticket_id, ticket)

    if auto_refresh:
        time.sleep(int(refresh_interval))
        st.rerun()


def _render_ticket_card(ticket_id: str, ticket: dict | None) -> None:
    with st.container(border=True):
        header_col1, header_col2 = st.columns([3, 1])
        header_col1.markdown(f"**Ticket:** `{ticket_id}`")

        if ticket is None:
            header_col2.markdown(_status_badge("UNKNOWN"), unsafe_allow_html=True)
            st.caption("No details yet — refresh to fetch.")
            return

        status = ticket.get("Status", "UNKNOWN")
        header_col2.markdown(_status_badge(status), unsafe_allow_html=True)

        start_time = ticket.get("StartTime")
        if start_time is not None:
            elapsed = _elapsed_seconds(start_time)
            st.caption(
                f"StartTime: {start_time.isoformat() if hasattr(start_time, 'isoformat') else start_time}"
                f" — elapsed: {elapsed:.0f}s"
            )

        estimated_wait = ticket.get("EstimatedWaitTime")
        if estimated_wait is not None:
            st.caption(f"EstimatedWaitTime: {estimated_wait}s")

        status_reason = ticket.get("StatusReason")
        status_message = ticket.get("StatusMessage")
        if status_reason:
            st.markdown(
                f"<div style='background:#ffebee;border-left:4px solid #f44336;"
                f"padding:8px 12px;border-radius:4px;margin:4px 0;'>"
                f"<b>StatusReason:</b> {status_reason}</div>",
                unsafe_allow_html=True,
            )
        if status_message:
            st.markdown(
                f"<div style='background:#fff3e0;border-left:4px solid #ff9800;"
                f"padding:8px 12px;border-radius:4px;margin:4px 0;'>"
                f"<b>StatusMessage:</b> {status_message}</div>",
                unsafe_allow_html=True,
            )

        players = ticket.get("Players", []) or []
        if players:
            with st.expander(f"Players ({len(players)})", expanded=False):
                for player in players:
                    st.markdown(f"**PlayerId:** `{player.get('PlayerId', '')}`")
                    team = player.get("Team")
                    if team:
                        st.markdown(f"Team: `{team}`")
                    attributes = player.get("PlayerAttributes", {}) or {}
                    if attributes:
                        st.markdown("PlayerAttributes:")
                        st.json(_render_player_attributes(attributes))
                    latency = player.get("LatencyInMs") or {}
                    if latency:
                        st.markdown("LatencyInMs:")
                        st.json(latency)
                    st.divider()

        if status == "COMPLETED":
            game_session = ticket.get("GameSessionConnectionInfo", {}) or {}
            arn = game_session.get("GameSessionArn", "")
            ip = game_session.get("IpAddress", "")
            port = game_session.get("Port", "")
            dns = game_session.get("DnsName", "")
            st.markdown("**Game Session**")
            st.code(
                json.dumps(
                    {
                        "GameSessionArn": arn,
                        "IpAddress": ip,
                        "DnsName": dns,
                        "Port": port,
                    },
                    indent=2,
                ),
                language="json",
            )
            matched = game_session.get("MatchedPlayerSessions", []) or []
            if matched:
                st.markdown("**MatchedPlayerSessions**")
                st.table(
                    [
                        {
                            "PlayerId": m.get("PlayerId", ""),
                            "PlayerSessionId": m.get("PlayerSessionId", ""),
                        }
                        for m in matched
                    ]
                )
            # Team assignments are on the players themselves
            team_map = [
                {"PlayerId": p.get("PlayerId", ""), "Team": p.get("Team", "")}
                for p in players
            ]
            if team_map:
                st.markdown("**Team assignments**")
                st.table(team_map)


def _render_player_attributes(attributes: dict) -> dict:
    """Flatten AWS PlayerAttributes into a readable dict.

    Each entry is {"N": ...} / {"S": ...} / {"SL": ...} / {"SDM": ...}.
    """
    flat: dict[str, Any] = {}
    for name, entry in attributes.items():
        if not isinstance(entry, dict):
            flat[name] = entry
            continue
        for type_key in ("N", "S", "SL", "SDM"):
            if type_key in entry:
                flat[name] = entry[type_key]
                break
        else:
            flat[name] = entry
    return flat


def _status_badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "#607d8b")
    return (
        f"<span style='background:{color};color:white;padding:4px 10px;"
        f"border-radius:12px;font-weight:600;font-size:0.85em;'>{status}</span>"
    )


def _elapsed_seconds(start_time: Any) -> float:
    if isinstance(start_time, datetime):
        start = start_time
    else:
        try:
            start = datetime.fromisoformat(str(start_time))
        except ValueError:
            return 0.0
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - start).total_seconds()


def _stop_all_active_tickets(aws_config: dict) -> None:
    stopped = 0
    errors: list[str] = []
    for ticket_id in list(st.session_state["active_tickets"]):
        ticket = st.session_state["ticket_details"].get(ticket_id)
        status = ticket.get("Status") if ticket else None
        if status in TERMINAL_STATUSES:
            continue
        try:
            stop_ticket(aws_config["profile"], aws_config["region"], ticket_id)
            stopped += 1
        except (ClientError, BotoCoreError) as exc:
            errors.append(f"{ticket_id}: {exc}")

    if stopped:
        st.success(f"Stopped {stopped} ticket(s)")
    if errors:
        st.error("Some tickets failed to stop:\n" + "\n".join(errors))


def _clear_terminal_tickets() -> None:
    details = st.session_state["ticket_details"]
    remaining: list[str] = []
    for ticket_id in st.session_state["active_tickets"]:
        ticket = details.get(ticket_id)
        status = ticket.get("Status") if ticket else None
        if status in TERMINAL_STATUSES:
            details.pop(ticket_id, None)
            continue
        remaining.append(ticket_id)
    st.session_state["active_tickets"] = remaining


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main() -> None:
    st.set_page_config(page_title="FlexMatch Tool", layout="wide")
    init_session_state()

    st.title("AWS GameLift FlexMatch Tool")

    render_sidebar()

    tab_inspector, tab_start, tab_monitor = st.tabs(
        ["Ruleset Inspector", "Start Tickets", "Monitor Tickets"]
    )

    with tab_inspector:
        render_ruleset_inspector()
    with tab_start:
        render_start_tickets()
    with tab_monitor:
        render_monitor_tickets()


if __name__ == "__main__":
    main()
