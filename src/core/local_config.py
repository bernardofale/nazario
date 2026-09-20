"""Local-only source endpoints (git-ignored — NOT committed).

fetch_club_stats.py and the manual results-feed curl read these. Kept out of
version control so no provider URL ships with the public repo. Set your own
here (or via the matching environment variables) to run the fetchers.
"""
CLUB_STATS_API_BASE = "https://www.footymetrics.com/api/front/leagues/stats/players"
CLUB_STATS_REFERER = "https://www.footymetrics.com/"
RESULTS_FEED_URL = "https://worldcup26.ir/get/games"
