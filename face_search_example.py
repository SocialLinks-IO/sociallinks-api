import argparse
import os
import requests
from alive_progress import alive_bar
from concurrent.futures import ThreadPoolExecutor, as_completed


def make_request(domain, platform, name, photo_url, api_key):
    base_url = f"https://{domain}/api/social_mapper/{platform}/v2"
    params = {
        'fullname': name,
        'photo': photo_url,
        'max_profiles': 300,
        'only_first_equal': 1
    }
    headers = {
        'Authorization': api_key
    }
    response = requests.get(base_url, headers=headers, params=params)
    if response.status_code == 200:
        json_data = response.json()
        data = json_data.get('results', json_data.get('result', []))
        result = [
            (item['url'], item.get('title', item.get('name', f"{item.get('first_name')} {item.get('last_name')}"))) for
            item in data]
        return result
    else:
        return []


def search_profiles(domain, platforms, name, photo_url, api_key):
    search_results = []
    with ThreadPoolExecutor(max_workers=len(platforms)) as executor:
        futures = {executor.submit(make_request, domain, platform, name, photo_url, api_key): platform for platform in
                   platforms}
        with alive_bar(len(platforms), title="Searching profiles") as bar:
            for future in as_completed(futures):
                platform = futures[future]
                try:
                    result = future.result()
                    if result:
                        search_results.extend(result)
                except Exception as exc:
                    print(f"Exception for platform {platform}: {exc}")
                bar()
    return search_results


def parse_args():
    parser = argparse.ArgumentParser(description='Search social media profiles based on name and photo.')
    parser.add_argument('--platforms', type=str, required=True,
                        help='Comma-separated list of platforms to search (e.g. twitter,youtube,myspace)')
    parser.add_argument('--name', type=str, required=True, help='Full name of the person to search for')
    parser.add_argument('--photo_url', type=str, required=True, help='URL of the photo to use for search')
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    platforms = args.platforms.split(',')
    name = args.name
    photo_url = args.photo_url

    domain = os.getenv('API_DOMAIN')
    if not domain:
        print("Error: Please set the API_DOMAIN environment variable.")
        exit(1)

    api_key = os.getenv('API_KEY')
    if not api_key:
        print("Error: Please set the API_KEY environment variable.")
        exit(1)

    results = search_profiles(domain, platforms, name, photo_url, api_key)

    for url, name in results:
        print(f"Name: {name}, URL: {url}")
