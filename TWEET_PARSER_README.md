# Tweet Parser and Sampler

A tool to parse your Twitter/X data export `tweets.js` file and create a representative sample of your original tweets (excluding retweets) for analysis or uploading to Claude.

## Features

- **Filters out all retweets** - Only keeps your original content
- **Stratified sampling** - Samples tweets evenly across your entire timeline to ensure temporal representation
- **Smart file splitting** - Automatically splits output into multiple files if needed (staying under 900k characters per file for Claude compatibility)
- **Configurable sample size** - Default 400 tweets (much more manageable than 12k!)

## Usage

### Basic usage:
```bash
python tweet_parser_sampler.py tweets.js
```

This will create a `tweet_samples/` directory with your sampled tweets.

### With custom options:
```bash
# Custom sample size (e.g., 500 tweets)
python tweet_parser_sampler.py tweets.js -n 500

# Custom output directory
python tweet_parser_sampler.py tweets.js -o my_tweets

# Use a random seed for reproducibility
python tweet_parser_sampler.py tweets.js --seed 42

# Combine options
python tweet_parser_sampler.py tweets.js -n 300 -o output --seed 123
```

### Get help:
```bash
python tweet_parser_sampler.py --help
```

## Output Format

Each tweet in the output file includes:
- Date/timestamp
- Full tweet text
- Engagement metrics (retweets and likes)

Example:
```
Date: Wed Oct 10 20:19:24 +0000 2018
Tweet: Just finished writing a new blog post about Python!
Engagement: 5 RTs, 23 Likes
--------------------------------------------------------------------------------
```

## Sample Size Recommendations

- **400 tweets** (default) - Good balance of coverage and manageability
- **200-300 tweets** - Quick overview of your tweet history
- **500-800 tweets** - More comprehensive sample
- **1000+** - Very thorough, but may create multiple files

The stratified sampling ensures you get tweets from throughout your entire Twitter history, not just recent ones.

## Where to Find tweets.js

1. Request your Twitter/X data archive from Settings → Your Account → Download an archive of your data
2. Wait for Twitter/X to prepare it (can take 24 hours)
3. Download and extract the ZIP file
4. Find `tweets.js` in the `data/` folder

## Running on Replit

If your tweets.js file is large:
1. Upload this script to Replit
2. Upload your tweets.js file
3. Run: `python tweet_parser_sampler.py tweets.js`
4. Download the output files from the `tweet_samples/` directory
