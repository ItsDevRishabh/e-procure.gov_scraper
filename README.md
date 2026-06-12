# e-procure.gov_scraper

# GeM-CPPP Tender Data Extraction Script

## Overview
This project is a robust web scraper for extracting tender data from the GeM-CPPP (Government e-Marketplace - Central Public Procurement Portal) website. It uses Selenium WebDriver to automate browser actions, handle network interruptions, and ensure data is not lost if the connection drops. The script saves all extracted data to a CSV file and provides a preview file with the first 10 rows for quick inspection.

## Features
- Automated extraction of tender data from the GeM-CPPP portal
- Local web dashboard for non-technical users
- Resilient to network interruptions (auto-retry and resume)
- Per-row checkpointing for safe resumption
- Saves all data to a timestamped CSV file
- Creates a preview CSV file (`tender_data_preview.csv`) with the first 10 rows
- Uses Google Chrome in the background (no manual browser interaction needed)

## Requirements
- Windows 10/11 PC (recommended)
- Google Chrome browser (latest version recommended)
- Internet connection

## Setup Guide (Step-by-Step for Non-Technical Users)

### 1. Install Python
- Download Python 3.10 or newer from the official website: https://www.python.org/downloads/
- Run the installer. **IMPORTANT:** On the first screen, check the box that says `Add Python to PATH` before clicking "Install Now".

### 2. Download the Project Files
- Obtain the project folder (named `Scraper`) from your source (email, download link, or USB drive).
- Place the `Scraper` folder anywhere on your computer (e.g., Desktop or Documents).

### 3. Open a Command Prompt in the Project Folder
- Open the `Scraper` folder in Windows Explorer.
- In the folder, hold the `Shift` key, right-click on a blank area, and select `Open PowerShell window here` or `Open Command window here`.

### 4. Set Up a Virtual Environment (Recommended)
- In the command window, type:
  ```powershell
  python -m venv localenv
  ```
- This creates a folder named `localenv` for your project’s Python environment.

### 5. Activate the Virtual Environment
- In the same command window, type:
  ```powershell
  .\localenv\Scripts\Activate.ps1
  ```
- You should see `(localenv)` at the start of the command line, indicating the environment is active.

### 6. Install Required Packages (using uv)
- With the environment active, install the required packages by running:
  ```powershell
  uv sync
  ```
- If there is no `pyproject.toml`, install the packages manually:
  ```powershell
  uv pip install selenium webdriver-manager requests
  ```

### 7. Ensure Google Chrome is Installed
- Download and install Google Chrome from https://www.google.com/chrome/ if not already installed.

### 8. Run the Script from Terminal
- In the same command window, run:
  ```powershell
  uv run python Scraper.py
  ```
- The script will start extracting data. Progress and status messages will appear in the window.
- When finished, you will see a message indicating the number of records saved and the name of the output CSV file (e.g., `tender_data_20251113_134545.csv`).
- A preview file named `tender_data_preview.csv` will also be created after the first 10 rows are scraped.

### 9. View the Output
- Open the output CSV files using Microsoft Excel or any spreadsheet program.
- `tender_data_preview.csv` contains the first 10 rows for quick checking.
- The main CSV file contains all extracted data.

## Web UI Demo Mode

Use this mode when showing the scraper to non-technical users.

1. Open a command window in the project folder.
2. Activate the virtual environment if you created one:
   ```powershell
   .\localenv\Scripts\Activate.ps1
   ```
3. Start the local dashboard:
   ```powershell
   uv run python web_ui.py
   ```
   If your virtual environment is already active, you can also run:
   ```powershell
   python web_ui.py
   ```
4. Open this address in a browser:
   ```text
   http://127.0.0.1:8000
   ```
5. Click **Start** on the page. The dashboard shows run status, generated CSV files, live logs, and a live extraction table that adds rows one by one as tender data is extracted.

To stop the dashboard itself, return to the command window and press `Ctrl+C`.

### 10. Troubleshooting
- **If you see an error about Chrome not found:**
  - Make sure Google Chrome is installed.
- **If you see a permissions error when activating the environment:**
  - Run PowerShell as Administrator and try again.
- **If you see a message about missing packages:**
  - Repeat step 6 to install the required packages.
- **If you lose internet connection:**
  - The script will automatically pause and resume when the connection is restored.

## Project Structure
```
Scraper/
├── Scraper.py                # Main script
├── web_ui.py                 # Local browser dashboard
├── pyproject.toml            # (Optional) Project metadata
├── requirements.txt          # (Optional) List of required packages
├── localenv/                 # Virtual environment (auto-created)
├── tender_data_YYYYMMDD_HHMMSS.csv  # Output data file
├── tender_data_preview.csv   # Preview file (first 10 rows)
└── ...
```

## Frequently Asked Questions

**Q: Do I need to keep the command window open?**
A: Yes, keep it open until the script finishes and you see the completion message.

**Q: Can I use this on Mac or Linux?**
A: This guide is for Windows. The script may work on Mac/Linux with minor changes, but support is not guaranteed for non-technical users.

**Q: What if I want to stop the script?**
A: Press `Ctrl+C` in the command window to stop it.

**Q: Where do I find the results?**
A: In the same folder as the script, look for files ending in `.csv`.

## Support
If you have any issues, contact the project maintainer or the person who provided you with this project for further assistance.
