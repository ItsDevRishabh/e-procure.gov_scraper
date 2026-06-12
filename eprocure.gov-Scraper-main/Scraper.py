#!/usr/bin/env python3
"""
GeM-CPPP Tender Data Extraction Script using Selenium
Version: Reliable Resume & WiFi Retry
This script adds robust per-row checkpointing and network retry so you never lose your data if connection drops.
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import csv
import json
import time
import logging
from datetime import datetime
import os

# NEW: Needed for network check
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def is_connected(url='https://eprocure.gov.in'):
    """Check internet connectivity by sending a HEAD request."""
    try:
        requests.head(url, timeout=5)
        return True
    except Exception:
        return False

class GemCpppScraper:
    def __init__(self):
        # Always delete checkpoint file to start fresh
        if os.path.exists("gemcppp_row_resume.txt"):
            os.remove("gemcppp_row_resume.txt")
        chrome_options = Options()
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        self.base_url = "https://eprocure.gov.in/cppp"
        self.all_data = []
        self.output_file = f"tender_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        self.live_data_file = "tender_data_live.jsonl"
        self.live_row_counter = 0
        self.preview_saved = False
        if os.path.exists(self.live_data_file):
            os.remove(self.live_data_file)

    def save_progress(self, page_num, row_index):
        try:
            with open("gemcppp_row_resume.txt", 'w') as f:
                f.write(f"{page_num},{row_index}\n")
        except Exception as e:
            logger.error(f"Could not write resume checkpoint: {e}")

    def load_progress(self):
        # Returns (start_page, start_row)
        if os.path.exists("gemcppp_row_resume.txt"):
            try:
                with open("gemcppp_row_resume.txt", 'r') as f:
                    page_str, row_str = f.read().strip().split(',')
                    return int(page_str), int(row_str)
            except Exception:
                pass
        return 1, 0

    def extract_detail_data_from_page(self) -> dict:
        """Extract detailed information directly from visible page text"""
        detail_data = {
            'Tender Type': '',
            'Name of Selected Bidder(s)': '',
            'Address of Selected Bidder(s)': '',
            'Number of Bids Received': '',
            'Contract Value': ''
        }

        try:
            try:
                rows = self.driver.find_elements(By.XPATH, "//table//tr")
                for row in rows:
                    row_text = row.text.strip()
                    if 'Tender Type' in row_text and ':' in row_text:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        for i, cell in enumerate(cells):
                            if cell.text.strip() == 'Tender Type':
                                if i + 2 < len(cells):
                                    detail_data['Tender Type'] = cells[i + 2].text.strip()
                            elif 'Number of bids received' in cell.text:
                                if i + 2 < len(cells):
                                    detail_data['Number of Bids Received'] = cells[i + 2].text.strip()
                    if 'Name of the selected bidder' in row_text:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        for i, cell in enumerate(cells):
                            if cell.text.strip() == 'Name of the selected bidder(s)':
                                if i + 2 < len(cells):
                                    detail_data['Name of Selected Bidder(s)'] = cells[i + 2].text.strip()
                            elif 'Contract Value' in cell.text:
                                if i + 2 < len(cells):
                                    val = cells[i + 2].text.strip()
                                    if val and val not in ['', ':', 'n/a', 'na', '-']:
                                        detail_data['Contract Value'] = val
                    if 'Address of the selected bidder' in row_text:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        for i, cell in enumerate(cells):
                            if cell.text.strip() == 'Address of the selected bidder(s)':
                                if i + 2 < len(cells):
                                    detail_data['Address of Selected Bidder(s)'] = cells[i + 2].text.strip()
            except Exception as e:
                logger.error(f"Row-based extraction failed: {e}")

            logger.info(
                f"✓ Extracted: Type='{detail_data['Tender Type']}' | Bidder='{detail_data['Name of Selected Bidder(s)']}' | Bids='{detail_data['Number of Bids Received']}' | Address='{detail_data['Address of Selected Bidder(s)']}' | Value='{detail_data['Contract Value']}'")
            return detail_data
        except Exception as e:
            logger.error(f"Error extracting detail: {e}")
            return detail_data

    def extract_table_data(self):
        """Extract table rows from current page"""
        rows = []
        try:
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_all_elements_located((By.TAG_NAME, "table"))
            )
            table = self.driver.find_element(By.ID, "table")
            tbody = table.find_element(By.TAG_NAME, "tbody")
            tr_elements = tbody.find_elements(By.TAG_NAME, "tr")

            logger.info(f"Found {len(tr_elements)} rows in table")

            for tr_idx, tr in enumerate(tr_elements):
                try:
                    cells = tr.find_elements(By.TAG_NAME, "td")
                    if len(cells) >= 5:
                        row_data = {
                            'row_index': tr_idx,
                            'Sl.No': cells[0].text.strip(),
                            'AOC Date': cells[1].text.strip(),
                            'e-Published Closing Date': cells[2].text.strip(),
                            'Title': cells[3].text.strip(),
                            'Organisation Name': cells[4].text.strip(),
                        }
                        rows.append(row_data)
                except Exception as e:
                    logger.warning(f"Error parsing row {tr_idx}: {e}")
                    continue

            return rows
        except Exception as e:
            logger.error(f"Error extracting table: {e}")
            return rows

    def save_preview_if_needed(self):
        """Save the first 10 rows to a preview file if not already saved and at least 10 rows exist."""
        if not self.preview_saved and len(self.all_data) >= 10:
            # Dynamically collect all possible keys from the first 10 rows
            preview_rows = self.all_data[:10]
            all_keys = set()
            for row in preview_rows:
                all_keys.update(row.keys())
            base_fields = [
                'Sl.No', 'AOC Date', 'e-Published Closing Date', 'Title',
                'Organisation Name', 'Tender Type', 'Name of Selected Bidder(s)',
                'Address of Selected Bidder(s)', 'Number of Bids Received', 'Contract Value'
            ]
            extra_fields = [k for k in all_keys if k not in base_fields]
            fieldnames = base_fields + sorted(extra_fields)
            with open('tender_data_preview.csv', 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for row in preview_rows:
                    row_out = {k: row.get(k, '') for k in fieldnames}
                    writer.writerow(row_out)
            self.preview_saved = True

    def save_live_row(self, row, page_num, row_index, status='Extracted'):
        """Append one extracted row for the web dashboard's live table."""
        self.live_row_counter += 1
        live_row = {
            'Serial': self.live_row_counter,
            'Page': page_num,
            'Row': row_index + 1,
            'Status': status,
            'Extracted At': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'Sl.No': row.get('Sl.No', ''),
            'AOC Date': row.get('AOC Date', ''),
            'e-Published Closing Date': row.get('e-Published Closing Date', ''),
            'Title': row.get('Title', ''),
            'Organisation Name': row.get('Organisation Name', ''),
            'Category': row.get('Tender Type', ''),
            'Tender Type': row.get('Tender Type', ''),
            'Name of Selected Bidder(s)': row.get('Name of Selected Bidder(s)', ''),
            'Address of Selected Bidder(s)': row.get('Address of Selected Bidder(s)', ''),
            'Number of Bids Received': row.get('Number of Bids Received', ''),
            'Contract Value': row.get('Contract Value', ''),
        }
        try:
            with open(self.live_data_file, 'a', encoding='utf-8') as live_file:
                live_file.write(json.dumps(live_row, ensure_ascii=False) + '\n')
        except Exception as e:
            logger.error(f"Could not write live dashboard row: {e}")

    def scrape_all_pages(self):
        base_list_url = "https://eprocure.gov.in/cppp/resultoftendersnew/cpppdata/byYzJWc1pXTjBBMTNoMVZtRnNkbVU9QTEzaDFBMTNoMUExM2gxTWpBeU5RPT1BMTNoMVVIVmliR2x6YUdWaw=="
        total_pages = 67

        start_page, start_row = self.load_progress()
        for page_num in range(start_page, total_pages + 1):
            if page_num == 1:
                page_url = base_list_url
            else:
                page_url = f"{base_list_url}?page={page_num}"

            logger.info(f"\n{'=' * 60}")
            logger.info(f"Fetching page {page_num}/{total_pages}")
            logger.info(f"{'=' * 60}")

            while not is_connected():
                logger.warning("No network connection. Waiting to retry...")
                time.sleep(10)
            self.driver.get(page_url)

            rows = self.extract_table_data()
            row_start = start_row if page_num == start_page else 0

            for tr_idx, row in enumerate(rows):
                # Resume at *exact* row
                if page_num == start_page and tr_idx < start_row:
                    continue


                self.save_progress(page_num, tr_idx)

                for _ in range(1000):  # Max retry limit
                    try:
                        logger.info(
                            f"  Page {page_num}: Processing row {tr_idx + 1}/{len(rows)} - {row['Title'][:50]}")
                        table = self.driver.find_element(By.ID, "table")
                        tbody = table.find_element(By.TAG_NAME, "tbody")
                        tr_elements = tbody.find_elements(By.TAG_NAME, "tr")
                        if tr_idx < len(tr_elements):
                            current_row = tr_elements[tr_idx]
                            cells = current_row.find_elements(By.TAG_NAME, "td")
                            if len(cells) >= 4:
                                link = cells[3].find_element(By.TAG_NAME, "a")
                                self.driver.execute_script("arguments[0].click();", link)
                                while not is_connected():
                                    logger.warning("Offline after opening row, waiting...")
                                    time.sleep(10)

                                detail_data = self.extract_detail_data_from_page()
                                row.update(detail_data)
                                self.all_data.append(row)
                                self.save_live_row(row, page_num, tr_idx, 'Extracted')
                                self.save_preview_if_needed()
                                self.driver.back()
                                while not is_connected():
                                    logger.warning("Offline on back, waiting...")
                                    time.sleep(10)
                                break  # Success, go to next row
                            else:
                                logger.warning(f"  Row {tr_idx + 1}: Not enough cells found")
                                self.all_data.append(row)
                                self.save_live_row(row, page_num, tr_idx, 'Basic row only')
                                self.save_preview_if_needed()
                                break
                        else:
                            logger.warning(f"  Row {tr_idx + 1}: Row index out of bounds")
                            self.all_data.append(row)
                            self.save_live_row(row, page_num, tr_idx, 'Basic row only')
                            self.save_preview_if_needed()
                            break
                    except Exception as e:
                        logger.error(f"  Row {tr_idx + 1}: Error - {e}")
                        try:
                            while not is_connected():
                                logger.warning("Offline after row error, waiting...")
                                time.sleep(10)
                            self.driver.get(page_url)
                            time.sleep(2)
                        except Exception:
                            logger.error("Retry to reload failed, will try again.")
                        continue

            # End of page: move row_start back to 0 for next page
            start_row = 0
            # Optionally trigger checkpoint file for CSV at every page

        # Remove progress file when done with all pages
        if os.path.exists("gemcppp_row_resume.txt"):
            os.remove("gemcppp_row_resume.txt")

    def save_to_csv(self):
        """Save all data to CSV"""
        if not self.all_data:
            logger.error("No data to save!")
            return

        try:
            # Dynamically collect all possible keys from all_data
            all_keys = set()
            for row in self.all_data:
                all_keys.update(row.keys())
            # Use the original field order, then add any extra keys at the end
            base_fields = [
                'Sl.No', 'AOC Date', 'e-Published Closing Date', 'Title',
                'Organisation Name', 'Tender Type', 'Name of Selected Bidder(s)',
                'Address of Selected Bidder(s)', 'Number of Bids Received', 'Contract Value'
            ]
            extra_fields = [k for k in all_keys if k not in base_fields]
            fieldnames = base_fields + sorted(extra_fields)

            with open(self.output_file, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for row in self.all_data:
                    # Ensure all keys are present for each row
                    row_out = {k: row.get(k, '') for k in fieldnames}
                    writer.writerow(row_out)

            logger.info(f"\n{'=' * 60}")
            logger.info(f"✓ Saved {len(self.all_data)} records to {self.output_file}")
            logger.info(f"{'=' * 60}")
        except Exception as e:
            logger.error(f"Error saving CSV: {e}")

    def run(self):
        """Main execution"""
        try:
            logger.info("Starting extraction...")
            self.scrape_all_pages()
            self.save_to_csv()
            logger.info("Extraction complete!")
        except Exception as e:
            logger.error(f"Fatal error: {e}")
        finally:
            self.driver.quit()
            logger.info("Driver closed")

if __name__ == "__main__":
    scraper = GemCpppScraper()
    scraper.run()
