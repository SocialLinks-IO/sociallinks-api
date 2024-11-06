import argparse
import os
import json
import requests
from collections import Counter
from statistics import median
from concurrent.futures import ThreadPoolExecutor, as_completed
from colorama import Fore, Style, init

# Initialize colorama for colored output
init(autoreset=True)

TIMEOUT = 300
LIMIT = 100

def detect_attribute(domain, text, api_key, attribute):
    base_url = f'https://{domain}/api/chatgpt/{attribute}?query={text}&task_id=&delayed=1&timeout=110&limit={LIMIT}&in_english=1'
    headers = {'Authorization': api_key}
    try:
        response = requests.get(base_url, headers=headers, timeout=TIMEOUT)
        if response.status_code == 200:
            return response.json().get('results', [])
    except requests.exceptions.RequestException as e:
        print(f"Request error for {attribute}: {e}")
    return []

def get_tweets(domain, query, api_key, search_type):
    endpoints = {
        'username': f"/api/twitter_v2/user/tweets?query={query}&type=all&limit={LIMIT}",
        'hashtags': f"/api/twitter_v2/search/tweets?hashtags={query}&type=all&limit={LIMIT}",
        'keywords': f"/api/twitter_v2/search/tweets?query={query}&type=all&limit={LIMIT}"
    }
    endpoint = endpoints.get(search_type)
    if not endpoint:
        raise ValueError("Invalid search type. Choose from 'username', 'hashtags', or 'keywords'.")

    base_url = f"https://{domain}{endpoint}"
    headers = {'Authorization': api_key}

    try:
        response = requests.get(base_url, headers=headers, timeout=TIMEOUT)
        if response.status_code == 200:
            return response.json().get('results', [])
    except requests.exceptions.RequestException as e:
        print(f"Request error for {search_type}: {e}")
    return []

def get_analytics(tweets):
    if not tweets:
        return {
            'total_tweets': 0,
            'total_likes': 0,
            'median_likes': 0,
            'total_views': 0,
            'median_views': 0
        }
    
    likes = [t['like_count'] for t in tweets]
    views = [t['view_count'] for t in tweets]
    
    return {
        'total_tweets': len(tweets),
        'total_likes': sum(likes),
        'median_likes': median(likes) if likes else 0,
        'total_views': sum(views),
        'median_views': median(views) if views else 0
    }

def analyze_tweets(tweets, domain, api_key):
    if not tweets:
        return {}, {}
    
    sentiments, topics = {}, {}
    with ThreadPoolExecutor() as executor:
        sentiment_futures = {executor.submit(detect_attribute, domain, t['text'], api_key, 'objects_sentiment'): t['id'] for t in tweets}
        for future in as_completed(sentiment_futures):
            tweet_id = sentiment_futures[future]
            try:
                sentiments[tweet_id] = future.result()
            except Exception as e:
                print(f"Error processing sentiment for tweet {tweet_id}: {e}")
        
        topic_futures = {executor.submit(detect_attribute, domain, t['text'], api_key, 'topics'): t['id'] for t in tweets}
        for future in as_completed(topic_futures):
            tweet_id = topic_futures[future]
            try:
                topics[tweet_id] = future.result()
            except Exception as e:
                print(f"Error processing topic for tweet {tweet_id}: {e}")
    
    return sentiments, topics

def parse_args():
    parser = argparse.ArgumentParser(description='Analyze tweets for sentiment and trend analysis.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--username', type=str, help='Twitter username to analyze')
    group.add_argument('--hashtags', type=str, help='Hashtags to search for')
    group.add_argument('--keywords', type=str, help='Keywords to search for')
    parser.add_argument('--verbose', action="store_true", help='Display detailed tweet information')
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()

    domain = os.getenv('API_DOMAIN')
    api_key = os.getenv('API_KEY')
    if not domain or not api_key:
        print("Error: Please set the API_DOMAIN and API_KEY environment variables.")
        exit(1)

    query, search_type = (args.username, 'username') if args.username else (args.hashtags, 'hashtags') if args.hashtags else (args.keywords, 'keywords')

    tweets_filename = f'tweets_{query}.json'
    if os.path.exists(tweets_filename):
        with open(tweets_filename) as f:
            tweets = json.load(f)
    else:
        print('Extracting tweets, please wait...')
        tweets = get_tweets(domain, query, api_key, search_type)
        if tweets:
            with open(tweets_filename, 'w') as f:
                json.dump(tweets, f, indent=4)

    if not tweets:
        print("No tweets found for the specified query.")
        exit(1)

    sentiments_filename = f'tweets_sentiments_{query}.json'
    topics_filename = f'tweets_topics_{query}.json'

    if os.path.exists(sentiments_filename) and os.path.exists(topics_filename):
        with open(sentiments_filename) as f:
            sentiments = json.load(f)
        with open(topics_filename) as f:
            topics = json.load(f)
    else:
        sentiments, topics = analyze_tweets(tweets, domain, api_key)
        with open(sentiments_filename, 'w') as f:
            json.dump(sentiments, f, indent=4)
        with open(topics_filename, 'w') as f:
            json.dump(topics, f, indent=4)

    analytics = get_analytics(tweets)
    print(f"""{Fore.GREEN}
Total tweets: {analytics['total_tweets']}
Total likes: {analytics['total_likes']}
Median likes per post: {analytics['median_likes']}
Total views: {analytics['total_views']}
Median views per post: {analytics['median_views']}
    """)

    negative_sentiments = [
        (tweet_id, s) for tweet_id, sentiment_list in sentiments.items()
        for s in sentiment_list if s.get('kind') == 'negative'
    ]

    if negative_sentiments:
        print(Fore.GREEN + "Top 5 negative sentiment topics with tweet links:")

        negative_counts = Counter([s['object'] for _, s in negative_sentiments])
        total_tweets_count = analytics['total_tweets']
        total_views_count = analytics['total_views']

        for sentiment, count in negative_counts.most_common(5):
            sentiment_tweets = [
                tweet for tweet in tweets
                if any(s['object'] == sentiment and s.get('kind') == 'negative' for s in sentiments.get(tweet['id'], []))
            ]
            sentiment_views = sum(tweet.get('view_count', 0) for tweet in sentiment_tweets)
            
            tweet_percentage = (count / total_tweets_count) * 100 if total_tweets_count else 0
            view_percentage = (sentiment_views / total_views_count) * 100 if total_views_count else 0

            print(f"{Fore.CYAN}- {sentiment} (found in {count} tweets, {view_percentage:.2f}% of total views):")
            top_related_tweets = sorted(sentiment_tweets, key=lambda x: x.get('view_count', 0), reverse=True)
            
            for tweet in top_related_tweets:
                if args.verbose:
                    tweet_url = f"https://x.com/_/status/{tweet['id']}"
                    print(f"   - URL: {Fore.LIGHTBLACK_EX+tweet_url}")
                print(f"  - {Fore.RED + tweet['text'].replace('\n', '')}")

    else:
        print(Fore.GREEN + "No negative sentiments found.")

    if tweets:
        top_viewed_tweets = sorted(tweets, key=lambda x: x.get('view_count', 0), reverse=True)[:3]
        print(Fore.GREEN + "\nTop 3 most viewed tweets:")
        for tweet in top_viewed_tweets:
            if args.verbose:
                print(f"- URL: {Fore.LIGHTBLACK_EX}https://x.com/_/status/{tweet['id']}")
                print(f"  Views: {tweet.get('view_count', 0)}, Likes: {tweet.get('like_count', 0)}")
            print(f"  - {Fore.CYAN + tweet['text'].replace('\n', '')}")
    else:
        print(Fore.RED + "No tweets found.")

    BLOCKLIST = ["I'm sorry"]

    all_topics = [t for topic_list in topics.values() for t in topic_list]
    filtered_topics = [t for t in all_topics if t.get('topic') not in BLOCKLIST]

    if filtered_topics:
        print(Fore.GREEN + "\nTrending topics:")
        topic_counts = Counter([tuple(sorted(t.items())) for t in filtered_topics])
        for topic, count in topic_counts.most_common(5):
            topic_obj = dict(topic)
            print(f"  - {topic_obj['topic']}: {count}")
    else:
        print("No topics found after applying blocklist.")