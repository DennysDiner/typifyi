#!/usr/bin/env python3
"""
Tasmania Parliament Hansard PDF Downloader

This script uses Selenium to navigate the Parliament website and download
Hansard PDFs, bypassing 403 protection on automated requests.

Usage:
    python 1_download_pdfs.py --start-year 1979 --end-year 2025 --output-dir ./pdfs
"""

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import requests


class HansardDownloader:
    def __init__(self, output_dir="./pdfs", delay=2.0):
        """
        Initialize the Hansard downloader.

        Args:
            output_dir: Directory to save PDFs
            delay: Delay between requests in seconds (be respectful!)
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.session = requests.Session()

        # Metadata tracking
        self.metadata_file = self.output_dir / "download_metadata.json"
        self.metadata = self._load_metadata()

        # Initialize Selenium WebDriver
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')  # Run in background
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')

        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 10)

    def _load_metadata(self):
        """Load existing download metadata."""
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r') as f:
                return json.load(f)
        return {"downloads": [], "failed": [], "last_run": None}

    def _save_metadata(self):
        """Save download metadata."""
        self.metadata["last_run"] = datetime.now().isoformat()
        with open(self.metadata_file, 'w') as f:
            json.dump(self.metadata, f, indent=2)

    def discover_hansard_urls(self, start_year=1979, end_year=2025):
        """
        Discover Hansard PDF URLs by exploring the search portal.

        This method navigates the search interface to find all available PDFs.

        Args:
            start_year: Starting year for Hansard records
            end_year: Ending year for Hansard records

        Returns:
            List of dicts with PDF metadata: {url, date, house, title}
        """
        print(f"Discovering Hansard PDFs from {start_year} to {end_year}...")

        pdf_urls = []

        # Method 1: Direct search portal navigation
        search_url = "https://search.parliament.tas.gov.au/"

        try:
            self.driver.get(search_url)
            time.sleep(2)

            # Try to find search interface elements
            # This will need to be customized based on actual site structure
            print("Navigating search portal...")

            for year in range(start_year, end_year + 1):
                print(f"Searching year {year}...")

                # This is a placeholder - actual implementation depends on
                # the search portal's structure
                # You'll need to:
                # 1. Interact with year selector
                # 2. Submit search
                # 3. Extract PDF links from results
                # 4. Paginate through results if needed

                time.sleep(self.delay)

        except Exception as e:
            print(f"Error during discovery: {e}")

        # Method 2: Pattern-based URL generation (if URLs follow predictable pattern)
        # Example pattern discovered from web search:
        # https://www.parliament.tas.gov.au/__data/assets/pdf_file/0004/100003/HA-Thursday-4-December-2025-Draft-Full-Text.pdf

        # This would require manually discovering the pattern through exploration

        return pdf_urls

    def download_pdf(self, url, filename=None):
        """
        Download a single PDF using Selenium-obtained cookies.

        Args:
            url: URL of the PDF
            filename: Optional custom filename

        Returns:
            Path to downloaded file or None if failed
        """
        if not filename:
            filename = os.path.basename(urlparse(url).path)

        output_path = self.output_dir / filename

        # Skip if already downloaded
        if output_path.exists():
            print(f"Already exists: {filename}")
            return output_path

        try:
            # Navigate to the PDF URL with Selenium to get cookies
            self.driver.get(url)
            time.sleep(1)

            # Get cookies from Selenium session
            cookies = self.driver.get_cookies()
            session_cookies = {cookie['name']: cookie['value'] for cookie in cookies}

            # Download using requests with Selenium cookies
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://www.parliament.tas.gov.au/'
            }

            response = self.session.get(url, cookies=session_cookies, headers=headers, timeout=30)

            if response.status_code == 200:
                with open(output_path, 'wb') as f:
                    f.write(response.content)

                print(f"Downloaded: {filename} ({len(response.content) / 1024:.1f} KB)")

                # Record in metadata
                self.metadata["downloads"].append({
                    "url": url,
                    "filename": filename,
                    "timestamp": datetime.now().isoformat(),
                    "size_bytes": len(response.content)
                })

                time.sleep(self.delay)  # Be respectful
                return output_path
            else:
                print(f"Failed: {filename} (Status {response.status_code})")
                self.metadata["failed"].append({"url": url, "status": response.status_code})
                return None

        except Exception as e:
            print(f"Error downloading {filename}: {e}")
            self.metadata["failed"].append({"url": url, "error": str(e)})
            return None

    def download_from_url_list(self, url_list_file):
        """
        Download PDFs from a pre-compiled list of URLs.

        Args:
            url_list_file: Path to text file with one URL per line
        """
        with open(url_list_file, 'r') as f:
            urls = [line.strip() for line in f if line.strip()]

        print(f"Found {len(urls)} URLs to download")

        for i, url in enumerate(urls, 1):
            print(f"[{i}/{len(urls)}] Processing: {url}")
            self.download_pdf(url)

            # Save metadata periodically
            if i % 10 == 0:
                self._save_metadata()

        # Final save
        self._save_metadata()

    def explore_site_structure(self):
        """
        Interactive exploration to understand site structure.
        Navigate the site and print useful information.
        """
        print("Exploring Tasmania Parliament Hansard structure...")

        urls_to_check = [
            "https://www.parliament.tas.gov.au/hansard",
            "https://search.parliament.tas.gov.au/",
        ]

        for url in urls_to_check:
            try:
                print(f"\n{'='*60}")
                print(f"Checking: {url}")
                print('='*60)

                self.driver.get(url)
                time.sleep(2)

                # Find all links
                links = self.driver.find_elements(By.TAG_NAME, "a")
                pdf_links = [link.get_attribute('href') for link in links
                            if link.get_attribute('href') and '.pdf' in link.get_attribute('href')]

                print(f"Found {len(pdf_links)} PDF links")
                for pdf_link in pdf_links[:10]:  # Show first 10
                    print(f"  - {pdf_link}")

                if len(pdf_links) > 10:
                    print(f"  ... and {len(pdf_links) - 10} more")

                # Save all PDF links found
                if pdf_links:
                    output_file = self.output_dir / f"discovered_urls_{urlparse(url).netloc}.txt"
                    with open(output_file, 'w') as f:
                        f.write('\n'.join(pdf_links))
                    print(f"\nSaved all PDF URLs to: {output_file}")

                time.sleep(self.delay)

            except Exception as e:
                print(f"Error exploring {url}: {e}")

    def close(self):
        """Clean up resources."""
        self.driver.quit()
        self._save_metadata()


def main():
    parser = argparse.ArgumentParser(description='Download Tasmania Parliament Hansard PDFs')
    parser.add_argument('--start-year', type=int, default=1979, help='Start year')
    parser.add_argument('--end-year', type=int, default=2025, help='End year')
    parser.add_argument('--output-dir', type=str, default='./pdfs', help='Output directory')
    parser.add_argument('--delay', type=float, default=2.0, help='Delay between requests (seconds)')
    parser.add_argument('--explore', action='store_true', help='Explore site structure only')
    parser.add_argument('--url-list', type=str, help='Download from URL list file')

    args = parser.parse_args()

    downloader = HansardDownloader(output_dir=args.output_dir, delay=args.delay)

    try:
        if args.explore:
            downloader.explore_site_structure()
        elif args.url_list:
            downloader.download_from_url_list(args.url_list)
        else:
            urls = downloader.discover_hansard_urls(args.start_year, args.end_year)

            if urls:
                for i, url_data in enumerate(urls, 1):
                    print(f"[{i}/{len(urls)}] Downloading: {url_data.get('title', url_data['url'])}")
                    downloader.download_pdf(url_data['url'])
            else:
                print("No URLs discovered. Try running with --explore first to understand site structure.")

    finally:
        downloader.close()

    print("\nDownload complete!")
    print(f"Total downloads: {len(downloader.metadata['downloads'])}")
    print(f"Failed: {len(downloader.metadata['failed'])}")


if __name__ == '__main__':
    main()
