#!/usr/bin/env python3
"""
Tweet Parser and Sampler
Parses tweets.js from Twitter/X data export, filters out retweets,
and creates a stratified sample across time periods.
"""

import json
import re
import random
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from collections import defaultdict


def parse_tweets_js(file_path: str) -> List[Dict[str, Any]]:
    """Parse tweets.js file from Twitter data export."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Remove the JavaScript variable assignment
    # tweets.js typically starts with "window.YTD.tweets.part0 = " or similar
    json_match = re.search(r'\[.*\]', content, re.DOTALL)
    if json_match:
        json_str = json_match.group(0)
        tweets_data = json.loads(json_str)
    else:
        # Try parsing as direct JSON
        tweets_data = json.loads(content)

    return tweets_data


def is_retweet(tweet: Dict[str, Any]) -> bool:
    """Check if a tweet is a retweet."""
    tweet_obj = tweet.get('tweet', tweet)

    # Check for retweeted_status field
    if 'retweeted_status' in tweet_obj:
        return True

    # Check for RT @ in full_text
    full_text = tweet_obj.get('full_text', tweet_obj.get('text', ''))
    if full_text.startswith('RT @'):
        return True

    return False


def get_tweet_date(tweet: Dict[str, Any]) -> datetime:
    """Extract datetime from tweet."""
    tweet_obj = tweet.get('tweet', tweet)
    created_at = tweet_obj.get('created_at', '')

    # Twitter date format: "Wed Oct 10 20:19:24 +0000 2018"
    try:
        return datetime.strptime(created_at, '%a %b %d %H:%M:%S %z %Y')
    except:
        # Fallback: try ISO format
        try:
            return datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        except:
            return datetime.now()


def format_tweet_for_output(tweet: Dict[str, Any]) -> str:
    """Format a single tweet for text output."""
    tweet_obj = tweet.get('tweet', tweet)

    created_at = tweet_obj.get('created_at', 'Unknown date')
    full_text = tweet_obj.get('full_text', tweet_obj.get('text', ''))

    # Get metrics
    retweet_count = tweet_obj.get('retweet_count', 0)
    favorite_count = tweet_obj.get('favorite_count', 0)

    output = f"Date: {created_at}\n"
    output += f"Tweet: {full_text}\n"
    output += f"Engagement: {retweet_count} RTs, {favorite_count} Likes\n"
    output += "-" * 80 + "\n"

    return output


def stratified_sample_by_time(tweets: List[Dict[str, Any]], sample_size: int) -> List[Dict[str, Any]]:
    """
    Create a stratified sample of tweets across time periods.
    This ensures we get tweets from throughout the entire timeline.
    """
    if len(tweets) <= sample_size:
        return tweets

    # Sort tweets by date
    tweets_with_dates = [(get_tweet_date(t), t) for t in tweets]
    tweets_with_dates.sort(key=lambda x: x[0])

    # Divide into time buckets
    num_buckets = min(20, len(tweets) // 10)  # Create ~20 time periods
    bucket_size = len(tweets_with_dates) // num_buckets

    buckets = defaultdict(list)
    for i, (date, tweet) in enumerate(tweets_with_dates):
        bucket_idx = min(i // bucket_size, num_buckets - 1)
        buckets[bucket_idx].append(tweet)

    # Sample from each bucket proportionally
    sampled_tweets = []
    tweets_per_bucket = sample_size // len(buckets)
    remainder = sample_size % len(buckets)

    for bucket_idx, bucket_tweets in buckets.items():
        # Take proportional sample from each bucket
        bucket_sample_size = tweets_per_bucket
        if bucket_idx < remainder:
            bucket_sample_size += 1

        if len(bucket_tweets) <= bucket_sample_size:
            sampled_tweets.extend(bucket_tweets)
        else:
            sampled_tweets.extend(random.sample(bucket_tweets, bucket_sample_size))

    # Re-sort by date
    sampled_with_dates = [(get_tweet_date(t), t) for t in sampled_tweets]
    sampled_with_dates.sort(key=lambda x: x[0])

    return [t for _, t in sampled_with_dates]


def write_output_files(tweets: List[Dict[str, Any]], output_dir: str, max_chars_per_file: int = 900000):
    """
    Write tweets to text files, splitting into multiple files if needed.
    Claude's limit is around 1M characters, using 900k to be safe.
    """
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    current_file_num = 1
    current_content = []
    current_char_count = 0

    for tweet in tweets:
        tweet_text = format_tweet_for_output(tweet)
        tweet_char_count = len(tweet_text)

        if current_char_count + tweet_char_count > max_chars_per_file and current_content:
            # Write current file
            filename = output_path / f"tweets_sample_part{current_file_num}.txt"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(''.join(current_content))
            print(f"Written {filename} ({current_char_count:,} characters)")

            # Start new file
            current_file_num += 1
            current_content = []
            current_char_count = 0

        current_content.append(tweet_text)
        current_char_count += tweet_char_count

    # Write final file
    if current_content:
        filename = output_path / f"tweets_sample_part{current_file_num}.txt"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(''.join(current_content))
        print(f"Written {filename} ({current_char_count:,} characters)")


def main():
    """Main execution function."""
    import argparse

    parser = argparse.ArgumentParser(description='Parse and sample tweets from tweets.js')
    parser.add_argument('input_file', help='Path to tweets.js file')
    parser.add_argument('-o', '--output-dir', default='tweet_samples',
                       help='Output directory for sample files (default: tweet_samples)')
    parser.add_argument('-n', '--sample-size', type=int, default=400,
                       help='Number of tweets to sample (default: 400)')
    parser.add_argument('--seed', type=int, help='Random seed for reproducibility')

    args = parser.parse_args()

    if args.seed:
        random.seed(args.seed)

    print(f"Reading tweets from {args.input_file}...")
    all_tweets = parse_tweets_js(args.input_file)
    print(f"Total tweets found: {len(all_tweets):,}")

    # Filter out retweets
    print("Filtering out retweets...")
    original_tweets = [t for t in all_tweets if not is_retweet(t)]
    print(f"Original tweets (non-retweets): {len(original_tweets):,}")

    # Create stratified sample
    print(f"Creating stratified sample of {args.sample_size} tweets...")
    sampled_tweets = stratified_sample_by_time(original_tweets, args.sample_size)
    print(f"Sampled {len(sampled_tweets):,} tweets")

    # Get date range
    if sampled_tweets:
        dates = [get_tweet_date(t) for t in sampled_tweets]
        print(f"Date range: {min(dates).strftime('%Y-%m-%d')} to {max(dates).strftime('%Y-%m-%d')}")

    # Write output
    print(f"\nWriting output to {args.output_dir}/...")
    write_output_files(sampled_tweets, args.output_dir)

    print("\n✓ Done!")
    print(f"Sample files created in '{args.output_dir}/' directory")


if __name__ == '__main__':
    main()
