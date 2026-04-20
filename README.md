# FlexMatch Tool

Strumento Streamlit per testare il matchmaking AWS GameLift FlexMatch. Generico e riutilizzabile: nessun dato specifico di gioco è hardcoded — profilo AWS, regione e nome della matchmaking configuration sono inseriti a runtime dalla sidebar.

## Requisiti

- Python 3.10+ (testato con 3.14)
- Un profilo AWS configurato con permessi per GameLift (`gamelift:DescribeMatchmakingConfigurations`, `gamelift:DescribeMatchmakingRuleSets`, `gamelift:StartMatchmaking`, `gamelift:DescribeMatchmaking`, `gamelift:StopMatchmaking`)
- AWS credentials accessibili a boto3 (file `~/.aws/credentials` + `~/.aws/config`, oppure SSO login già fatto)

## Setup

1. **Clona / entra nella cartella del progetto**
   ```bash
   cd c:\Users\Nicola\Desktop\FlexMatchTool
   ```

2. **(Consigliato) Crea un virtual environment**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. **Installa le dipendenze**
   ```bash
   python -m pip install -r requirements.txt
   ```

## Avvio

Dalla cartella del progetto:

```bash
python -m streamlit run app.py
```

Streamlit aprirà automaticamente il browser su `http://localhost:8501`.

> **Nota:** usare `python -m streamlit` evita problemi di PATH quando l'eseguibile `streamlit` è installato nella user site-packages. In alternativa, aggiungere a PATH la cartella `Scripts` della tua installazione Python (es. `C:\Users\<user>\AppData\Roaming\Python\Python314\Scripts`) e poi usare direttamente `streamlit run app.py`.

## Configurazione AWS

Il tool usa `boto3.Session(profile_name=...)`, quindi qualsiasi profilo presente in `~/.aws/credentials` o `~/.aws/config` è utilizzabile.

Esempio `~/.aws/credentials`:
```ini
[mio-profilo]
aws_access_key_id = AKIA...
aws_secret_access_key = ...
```

Per SSO:
```bash
aws sso login --profile mio-profilo
```

## Utilizzo

### 1. Sidebar — AWS Config
- **AWS Profile Name**: nome del profilo (vuoto = default)
- **AWS Region**: regione in cui si trova la matchmaking configuration (es. `eu-west-1`)
- **Matchmaking Configuration Name**: nome esatto della configuration su GameLift
- Premi **Load Configuration**: il tool scarica la configuration e il ruleset associato

### 2. Tab "Ruleset Inspector"
Mostra in modo strutturato il ruleset caricato: algoritmo, team, player attributes, regole (con proprietà specifiche per tipo: `batchDistance`, `comparison`, `distance`, `collection`, `latency`, `compound`) ed expansions.

### 3. Tab "Start Tickets"
- Imposta quanti ticket/player creare
- Compila i player attributes (il form è generato dinamicamente dal ruleset)
- Aggiungi coppie regione/latenza se necessario
- Premi **Start Matchmaking**: crea N ticket con `PlayerId` nel formato `test-player-<N>-<uuid>`

### 4. Tab "Monitor Tickets"
- Mostra stato di tutti i ticket attivi con badge colorato
- Visualizza `StatusReason` / `StatusMessage` evidenziati in caso di errore
- Per ticket `COMPLETED`: mostra GameSession ARN, IP, porta, e assegnazioni di team
- **Auto-refresh** configurabile, oppure refresh manuale
- Possibile aggiungere manualmente ticket ID esistenti
- **Stop All Tickets**: annulla tutti i ticket non terminati
- **Clear Terminal Tickets**: rimuove dalla lista i ticket già conclusi

## Troubleshooting

**`streamlit : The term 'streamlit' is not recognized...`**
Usa `python -m streamlit run app.py` oppure aggiungi la cartella `Scripts` di Python al PATH.

**`NoCredentialsError` / `ProfileNotFound`**
Verifica che il profilo esista in `~/.aws/credentials` o che `aws sso login --profile <nome>` sia stato eseguito.

**`ResourceNotFoundException` sul load**
Controlla che il nome della matchmaking configuration sia esatto e che la regione sia quella giusta (le configurations sono per-region).

**Ticket bloccato in `SEARCHING` senza match**
Controlla `StatusReason` e `StatusMessage` nel tab Monitor: indicano quale regola ha fallito. Spesso servono più ticket in parallelo per soddisfare i `minPlayers` del team.

## File

- `app.py` — applicazione Streamlit (singolo file)
- `requirements.txt` — dipendenze Python
