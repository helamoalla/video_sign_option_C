import sys
import re
import time
import requests
from pathlib import Path
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import xml.dom.minidom
from urllib.parse import urljoin


BASE_DIR = Path(__file__).resolve().parent

BASE_URL = "https://www.sign-lang.uni-hamburg.de/dicta-sign/portal/concepts/"

CONCEPT_LISTS = {
    "french": "concepts_fre.html",
    "german": "concepts_deu.html",
    "english": "concepts_eng.html",
}

CONVERSION_FILE = BASE_DIR / "conversionSpreadSheet.txt"

# Correct CWASA folders
SIGML_ROOT = Path("external/alsl_avatar/data/sigml")

SIGN_LANGUAGE_FOLDERS = {
    "BSL": "BSL",
    "DGS": "dgs",
    "LSF": "lsf",
    "GSL": "GSL",
}

SIGN_LANGUAGES = ["BSL", "DGS", "LSF", "GSL"]


def fetch_soup(url):
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    response.encoding = "utf-8"
    return BeautifulSoup(response.text, "html.parser")


def clean_filename(text):
    text = text.strip().lower()
    text = re.sub(r"[^\w\-Α-Ωα-ωάέήίόύώϊϋΐΰ]+", "_", text, flags=re.UNICODE)
    return text.strip("_") or "unknown"


def load_conversion_lines():
    if not CONVERSION_FILE.exists():
        raise FileNotFoundError(f"Conversion file not found: {CONVERSION_FILE}")

    with open(CONVERSION_FILE, "r", encoding="utf-8") as f:
        return f.readlines()


def hamnosys_char_to_code(char):
    code = char.encode("unicode_escape").decode()
    code = code.replace("\\u", "").upper()
    return code


def hamnosys_to_codes(hamnosys_text):
    codes = []

    for char in hamnosys_text:
        code = hamnosys_char_to_code(char)

        if len(code) == 4:
            codes.append(code)

    return codes


def find_sigml_tag(code, conversion_lines):
    for line in conversion_lines:
        if code in line.upper():
            return line.split(",")[0].strip()

    return None


def hamnosys_to_sigml(hamnosys_text, gloss, conversion_lines):
    data = ET.Element("sigml")

    hns_sign = ET.SubElement(data, "hns_sign")
    hns_sign.set("gloss", gloss)

    ET.SubElement(hns_sign, "hamnosys_nonmanual")
    manual = ET.SubElement(hns_sign, "hamnosys_manual")

    codes = hamnosys_to_codes(hamnosys_text)

    missing_codes = []

    for code in codes:
        sigml_tag = find_sigml_tag(code, conversion_lines)

        if sigml_tag:
            ET.SubElement(manual, sigml_tag)
        else:
            missing_codes.append(code)

    if missing_codes:
        print(f"  Warning: missing codes for {gloss}: {missing_codes}")

    data_str = ET.tostring(data, encoding="unicode")
    dom = xml.dom.minidom.parseString(data_str)

    return dom.toprettyxml(encoding="UTF-8").decode("utf-8")


def get_concept_links(language):
    url = urljoin(BASE_URL, CONCEPT_LISTS[language])
    soup = fetch_soup(url)

    links = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        word = a.get_text(strip=True)

        if href.startswith("cs/") and word:
            links.append({
                "word": word,
                "url": urljoin(BASE_URL, href)
            })

    return links


def looks_like_hamnosys(text):
    return any(0xE000 <= ord(ch) <= 0xF8FF for ch in text)


def extract_hamnosys_entries(concept_url):
    soup = fetch_soup(concept_url)

    lines = [
        line.strip()
        for line in soup.get_text("\n").splitlines()
        if line.strip()
    ]

    entries = []

    for i, line in enumerate(lines):
        if line in SIGN_LANGUAGES:
            sign_language = line

            local_word = lines[i - 1] if i > 0 else sign_language

            for j in range(i + 1, min(i + 20, len(lines))):
                possible = lines[j]

                if possible in SIGN_LANGUAGES:
                    break

                if looks_like_hamnosys(possible):
                    gloss = lines[j - 1] if j - 1 > i else local_word

                    entries.append({
                        "sign_language": sign_language,
                        "local_word": local_word,
                        "gloss": gloss,
                        "hamnosys": possible
                    })

                    break

    return entries


def save_sigml_file(sign_language, local_word, gloss, sigml):
    folder_name = SIGN_LANGUAGE_FOLDERS.get(sign_language)

    if not folder_name:
        return None

    folder = SIGML_ROOT / folder_name
    folder.mkdir(parents=True, exist_ok=True)

    filename = f"{clean_filename(local_word)}.sigml"
    file_path = folder / filename

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(sigml)

    return file_path


def scrape_and_generate(language="french", limit=None):
    SIGML_ROOT.mkdir(parents=True, exist_ok=True)

    conversion_lines = load_conversion_lines()
    concept_links = get_concept_links(language)

    if limit:
        concept_links = concept_links[:limit]

    print(f"Found {len(concept_links)} concepts for {language}")
    print(f"Output folder: {SIGML_ROOT.resolve()}")
    print()

    total_saved = 0

    for index, concept in enumerate(concept_links, start=1):
        source_word = concept["word"]
        url = concept["url"]

        print(f"[{index}/{len(concept_links)}] Processing: {source_word}")

        try:
            entries = extract_hamnosys_entries(url)

            if not entries:
                print("  No HamNoSys found")
                continue

            for entry in entries:
                sign_language = entry["sign_language"]
                local_word = entry["local_word"]
                gloss = entry["gloss"]
                hamnosys = entry["hamnosys"]

                print(f"  Found {sign_language}: {local_word} / {gloss}")

                sigml = hamnosys_to_sigml(
                    hamnosys_text=hamnosys,
                    gloss=gloss,
                    conversion_lines=conversion_lines
                )

                file_path = save_sigml_file(
                    sign_language=sign_language,
                    local_word=local_word,
                    gloss=gloss,
                    sigml=sigml
                )

                if file_path:
                    total_saved += 1
                    print(f"  Saved: {file_path}")

        except Exception as e:
            print(f"  Error with {source_word}: {e}")

        time.sleep(0.3)

    print()
    print(f"Done. Total files saved: {total_saved}")
    print(f"Files are here: {SIGML_ROOT.resolve()}")


if __name__ == "__main__":
    language = sys.argv[1] if len(sys.argv) > 1 else "french"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None

    if language not in CONCEPT_LISTS:
        print("Invalid language. Use: french, german, or english")
        sys.exit(1)

    scrape_and_generate(language=language, limit=limit)