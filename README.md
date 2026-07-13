# AI Activity Logger (Windows Background Service)

A lightweight Windows background utility that automatically captures and records your conversations with desktop AI applications (such as Claude Desktop, ChatGPT, etc.). It filters out application navigation bar labels, timestamps, and settings menus to log only the actual chat messages (user questions and assistant replies) to a structured JSON Lines file on disk.

## Features

- **System Tray Management**: Small taskbar icon to toggle recording ON/OFF, open the log folder, or exit.
- **UIA Adaptability**: Supports specialized config-based JSON selectors for high-fidelity parsing (adapters), falling back to robust generic DOM text-walking heuristics if no adapter is specified.
- **Debounced Logging**: Suppresses streaming noise by waiting for a short stability duration (no text changes) before committing a message.
- **Session Tracking**: Keyed conversation tracking that automatically groups logs by conversation ID, rotating the ID on window title changes or after 30 minutes of inactivity.
- **Multi-Desktop Aware**: Works seamlessly inside restricted sandboxes or multi-desktop virtual workstations by binding thread operations to the active interactive `Default` desktop.

---

## 1. Installation & Run

### Prerequisites
- Windows OS
- Python 3.11 or higher

### Steps
1. Navigate to the project directory:
   ```bash
   cd c:\Projects\logging-app
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   *Required packages:*
   - `uiautomation` (Python wrapper for UI Automation)
   - `pystray` (System tray integration)
   - `Pillow` (Icon generation)
   - `psutil` (Running process scanning)
   - `tzlocal` (Timezone mapping)

3. Launch the service:
   ```bash
   python main.py
   ```
   *Note: If target apps (e.g. ChatGPT, Claude) are launched with administrator privileges, this logger must also be run in a Command Prompt as Administrator to access their UIA structures.*

---

## 2. Operation & System Tray Icon

- On startup, a glowing system tray icon appears in your Windows taskbar.
- **Green Icon**: Logging is active and scanning matched running apps every `poll_interval_seconds` (default: 1.5s).
- **Slate Gray Icon**: Logging is paused. The polling thread goes idle and releases UIA calls.
- **Right-Click Menu Options**:
  - **Toggle Logging**: Toggle active capturing state.
  - **Open Log Folder**: Opens the local `logs/` directory inside the project root in Windows File Explorer.
  - **Quit**: Safely terminates the background polling thread and exits.

---

## 3. Configuration & Extension

### Target Application List (`config/apps.json`)
To instruct the logger to watch new applications, add their executable names (case-insensitive) to `config/apps.json`:
```json
[
  "Claude.exe",
  "ChatGPT.exe",
  "Gemini.exe"
]
```

### Settings (`config/settings.json`)
You can tweak performance and parsing parameters:
```json
{
  "poll_interval_seconds": 1.5,      // Interval between UI scans
  "idle_timeout_minutes": 30,       // Duration after which a new conversation ID is generated
  "min_text_length": 10,             // Ignore text nodes shorter than this (removes button debris)
  "debounce_polls": 2,               // Wait N consecutive scans with no changes to finalize streaming replies
  "ignored_text_patterns": [         // Skip text nodes containing these substrings
    "Send", "Cancel", "Attach", "Ctrl+", "Enter to send", "Copy code"
  ]
}
```

---

## 4. Writing Adapters (`config/adapters.json`)

Adapters allow you to specify the exact structural selectors (Automation ID, Class Name, Control Type) to parse message rows within an app window.

### Worked Example: Claude Desktop
To write an adapter for Claude Desktop:
1. Download a tool like **Accessibility Insights for Windows** or **Inspect.exe** (Windows SDK).
2. Open Claude Desktop, launch the inspection tool, and click on the chat pane.
3. Locate the scrollable container. You will see a `Group` control with a ClassName like `overflow-y-auto`.
4. Inspect a single message element. You will find it is a `Group` control with a ClassName like `font-claude-message`.
5. Map this structure into `config/adapters.json`:

```json
{
  "Claude.exe": {
    "chat_pane_selector": {
      "ControlType": "Group",
      "ClassName": "overflow-y-auto"
    },
    "message_element_selector": [
      {
        "ControlType": "Group",
        "ClassName": "font-claude-message"
      }
    ],
    "role_selectors": {
      "user": {
        "ClassName": "bg-accent"
      }
    }
  }
}
```

---

## 5. Storage Schema & Log Output

Logs are safely appended as **JSON Lines** (`.jsonl`) to:
`logs/<username>/logs.jsonl` (inside the project root folder, isolated per OS user)

### Record Schema
Each line in `logs.jsonl` is a standalone JSON record:
```json
{
  "id": "uuid4 string",
  "source": "chatgpt",
  "conversation_id": "string",
  "user_content": "User prompt content",
  "assistant_content": "Assistant reply content",
  "timestamp_utc": "ISO 8601 UTC timestamp",
  "timezone": "IANA timezone (e.g. America/New_York)",
  "timestamp_local": "ISO 8601 local timestamp"
}
```

### Parsing JSONL to JSON Array
To merge the log file lines into a single standard JSON array in Python:
```python
import json

with open("logs.jsonl", "r", encoding="utf-8") as f:
    records = [json.loads(line) for line in f if line.strip()]

with open("logs.json", "w", encoding="utf-8") as out:
    json.dump(records, out, indent=2, ensure_ascii=False)
```

---

## 6. Known Limitations

- **Windows Only**: Relies directly on the Microsoft Windows UI Automation COM API.
- **Lazy Rendering**: Electron/Chrome apps only expose their accessibility tree once queried by an active UIA client. The logger handles this by focusing the page web area, but a 0.3s delay can occur on the very first scan of a fresh window.
- **Adapter Maintenance**: Major UI updates to ChatGPT or Claude Desktop that change their internal CSS class names may render specific selectors stale. In this case, the logger automatically switches to the generic tree-walking fallback to maintain logging coverage.

---

## 7. Packaging into an Executable (.exe)

Although the utility is currently run via python commands, it can easily be packaged into a standalone background `.exe` using `PyInstaller`.

Run the following command from the root directory to generate a single executable file:
```bash
pip install pyinstaller
pyinstaller --noconsole --onefile --add-data "config;config" main.py
```
This packages Python, dependencies, and configuration templates into a single distributable binary inside the `dist/` directory.
