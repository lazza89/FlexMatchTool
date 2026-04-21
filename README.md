# FlexMatch Tool

Streamlit tool for testing AWS GameLift FlexMatch matchmaking. Generic and reusable: no game-specific data is hardcoded — AWS profile, region and matchmaking configuration name are entered at runtime from the sidebar.

## Requirements

- Python 3.10+ (tested with 3.14)
- An AWS profile with GameLift permissions (`gamelift:DescribeMatchmakingConfigurations`, `gamelift:DescribeMatchmakingRuleSets`, `gamelift:StartMatchmaking`, `gamelift:DescribeMatchmaking`, `gamelift:StopMatchmaking`)
- AWS credentials reachable by boto3 (`~/.aws/credentials` + `~/.aws/config`, or an active SSO session)

## Setup

1. **Clone / enter the project folder**
   ```bash
   cd c:\Users\Nicola\Desktop\FlexMatchTool
   ```

2. **(Recommended) Create a virtual environment**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   python -m pip install -r requirements.txt
   ```

## Run

From the project folder:

```bash
python -m streamlit run app.py
```

Streamlit will open the browser automatically at `http://localhost:8501`.

> **Note:** using `python -m streamlit` avoids PATH issues when the `streamlit` executable is installed in user site-packages. Alternatively, add Python's `Scripts` folder to PATH (e.g. `C:\Users\<user>\AppData\Roaming\Python\Python314\Scripts`) and use `streamlit run app.py` directly.

## AWS configuration

The tool uses `boto3.Session(profile_name=...)`, so any profile listed in `~/.aws/credentials` or `~/.aws/config` works.

Example `~/.aws/credentials`:
```ini
[my-profile]
aws_access_key_id = AKIA...
aws_secret_access_key = ...
```

For SSO:
```bash
aws sso login --profile my-profile
```

## Usage

### 1. Sidebar — AWS Config
- **AWS Profile Name**: profile name (empty = default)
- **AWS Region**: region where the matchmaking configuration lives (e.g. `eu-west-1`)
- **Matchmaking Configuration Name**: exact name of the GameLift matchmaking configuration
- Click **Load Configuration**: the tool fetches the configuration and its rule set

### 2. Tab "Ruleset Inspector"
Displays the loaded rule set in a structured way: algorithm, teams, player attributes, rules (with type-specific properties for `batchDistance`, `comparison`, `distance`, `collection`, `latency`, `compound`) and expansions.

### 3. Tab "Start Tickets"
Organized by **ticket**: each ticket is a separate matchmaking request and can hold one or more players. Multiple players inside the same ticket are treated by FlexMatch as a **party**.

- Each ticket shows its player list; per player you can:
  - Set a custom **Player ID** (or leave it blank to auto-generate `test-player-<ticket>-<player>-<uuid>`)
  - Fill in the **attributes** declared in the rule set (dynamic form: numbers, strings, lists, string→number maps). Labels show `— required` when the rule set declares no default, or `— default: X` otherwise
  - Add dedicated **region/latency** pairs for that player
  - Remove the player (when the ticket holds more than one)
- **Add player to this ticket**: adds a party-mate to the same ticket
- **Add empty ticket**: appends a new ticket with a single default player
- **Bulk quantity + Add N solo tickets**: quickly create N solo tickets with default values (typical for stress tests)
- **Reset drafts**: clears drafts and restores one default ticket
- **Start Matchmaking**: issues one `start_matchmaking` call per ticket with all its players, validates required attributes client-side first, and stores the returned ticket IDs in session

### 4. Tab "Monitor Tickets"
- Shows the status of every active ticket with a colored badge
- Highlights `StatusReason` / `StatusMessage` when matching fails
- For `COMPLETED` tickets: shows GameSession ARN, IP, port and team assignments
- Configurable **auto-refresh** plus manual refresh
- Manual ticket ID input to track externally-created tickets
- **Stop All Tickets**: cancels every non-terminal ticket
- **Clear Terminal Tickets**: removes finished tickets from the list

## Troubleshooting

**`streamlit : The term 'streamlit' is not recognized...`**
Use `python -m streamlit run app.py` or add Python's `Scripts` folder to PATH.

**`NoCredentialsError` / `ProfileNotFound`**
Check the profile exists in `~/.aws/credentials` or run `aws sso login --profile <name>`.

**`ResourceNotFoundException` on load**
Verify the matchmaking configuration name is correct and the region matches (configurations are per-region).

**`Invalid player; missing required attribute ...`**
The rule set requires an attribute with no default; fill it in the Start Tickets form (labels marked `— required`).

**Ticket stuck in `SEARCHING` with no match**
Check `StatusReason` / `StatusMessage` in the Monitor tab — they tell you which rule failed. Often you need more concurrent tickets to meet the team's `minPlayers`.

## Files

- `app.py` — Streamlit application (single file)
- `requirements.txt` — Python dependencies
