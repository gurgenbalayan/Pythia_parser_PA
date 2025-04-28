import json
import re
import aiohttp
from utils.logger import setup_logger
import os


STATE = os.getenv("STATE")
logger = setup_logger("scraper")



async def fetch_company_details(url: str) -> dict:
    try:
        match = re.search(r"/business/([A-Z0-9]+)/", url)
        if match:
            id = match.group(1)
            url_search = "https://file.dos.pa.gov/api/Records/businesssearch"
            payload = json.dumps({
                "SEARCH_VALUE": id,
                "STARTS_WITH_YN": True,
                "CRA_SEARCH_YN": False,
                "ACTIVE_ONLY_YN": False,
                "FILING_DATE": {
                    "start": None,
                    "end": None
                }
            })
            headers = {
                'Content-Type': 'application/json'
            }
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.post(url_search, data=payload) as response:
                    response.raise_for_status()
                    data = json.loads(await response.text())
                    result = await parse_html_name_agent(data)
                    record_num, id, name, agent = result["record_num"], result["id"], result["name"], result["agent"]
        else:
            logger.error(f"Error fetching data for query '{url}'")
            return []
        new_url = re.sub(r'(?<=business/)\d+(?=/)', id, url)
        async with aiohttp.ClientSession() as session:
            async with session.get(new_url) as response:
                response.raise_for_status()
                data = json.loads(await response.text())
                return await parse_html_details(data, record_num, id, name, agent)
    except Exception as e:
        logger.error(f"Error fetching data for query '{url}': {e}")
        return []
async def fetch_company_data(query: str) -> list[dict]:
    url = "https://file.dos.pa.gov/api/Records/businesssearch"

    payload = json.dumps({
        "SEARCH_VALUE": query,
        "SEARCH_FILTER_TYPE_ID": "1",
        "FILING_TYPE_ID": "",
        "STATUS_ID": "",
        "FILING_DATE": {
            "start": None,
            "end": None
        }
    })
    headers = {
        'Content-Type': 'application/json'
    }
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(url, data=payload) as response:
                response.raise_for_status()
                data = json.loads(await response.text())
                return await parse_html_search(data)
    except Exception as e:
        logger.error(f"Error fetching data for query '{query}': {e}")
        return []

async def parse_html_search(data: dict) -> list[dict]:
    results = []
    for entity_id, data_row in data["rows"].items():
        entity_name = data_row.get("TITLE", [""])[0]  # берём первую строку из TITLE
        status = data_row.get("STATUS", "")
        id = data_row.get("RECORD_NUM", "").lstrip("0")
        results.append({
                "state": STATE,
                "name": entity_name,
                "status": status,
                "id": entity_id,
                "url": f"https://file.dos.pa.gov/api/FilingDetail/business/{id}/false"
            })
    return results

async def parse_html_name_agent(data: dict) -> dict:
    for entity_id, data_row in data["rows"].items():
        entity_name = data_row.get("TITLE", [""])[0]  # берём первую строку из TITLE
        agent = data_row.get("AGENT", "")
        record_num = data_row.get("RECORD_NUM", "")
        return {
            "record_num": record_num,
            "id": entity_id,
            "name": entity_name,
            "agent": agent
        }


async def parse_html_details(data: dict, record_num: str, id: str, name: str, agent: str) -> dict:
    async def fetch_documents(record_num: str) -> list[dict]:
        url = f"https://file.dos.pa.gov/api/History/business/{record_num}"
        headers = {
            'Content-Type': 'application/json'
        }
        results = []
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    data = json.loads(await response.text())
                    base_url = "https://file.dos.pa.gov"
                    for amendment in data["AMENDMENT_LIST"]:
                        try:
                            download_link = base_url + amendment["DOWNLOAD_LINK"]
                            file_name = amendment["AMENDMENT_TYPE"]
                            file_date = amendment["AMENDMENT_DATE"]
                            results.append({
                                "name": file_name,
                                "date": file_date,
                                "link": download_link,
                            })
                        except Exception as e:
                            continue
                    return results
        except Exception as e:
            logger.error(f"Error fetching data for record_num '{record_num}': {e}")
            return []


    detail_map = {item["LABEL"]: item["VALUE"] for item in data.get("DRAWER_DETAIL_LIST", [])}
    mailing_address = detail_map.get("Mailing Address") or ""
    principal_address = detail_map.get("Principal Address") or ""
    registered_office = detail_map.get("Registered Office") or ""
    document_images = await fetch_documents(record_num)
    status = detail_map.get("Status")
    date_registered = detail_map.get("Initial Filing Date")
    entity_type = detail_map.get("Filing Type")
    governors = detail_map.get("Governors")
    interested_individuals = detail_map.get("Interested Individuals")
    return {
        "state": STATE,
        "name": name,
        "governors": governors,
        "interested_individuals": interested_individuals,
        "status": status.strip() if status else None,
        "registration_number": id,
        "registered_office": registered_office.strip() if date_registered else None,
        "date_registered": date_registered.strip() if date_registered else None,
        "entity_type": entity_type.strip() if entity_type else None,
        "agent_name": agent.strip() if agent else None,
        "principal_address": principal_address.strip() if principal_address else None,
        "mailing_address": mailing_address.strip() if mailing_address else None,
        "document_images": document_images
    }