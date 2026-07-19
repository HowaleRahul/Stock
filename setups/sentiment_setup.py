import pandas as pd
import yfinance as yf
from functools import lru_cache
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from setups.base import BaseSetup, SetupSignal

@lru_cache(maxsize=128)
def get_news_data(ticker: str) -> list:
    stock = yf.Ticker(ticker)
    return stock.news

class SentimentSetup(BaseSetup):
    """
    Evaluates news headline sentiment using VADER NLP on the most recent news
    pulled directly from Yahoo Finance.
    """
    
    @property
    def name(self) -> str:
        return "News Sentiment (NLP)"
        
    def evaluate(self, df: pd.DataFrame, ticker: str = "") -> SetupSignal:
        if not ticker:
            return SetupSignal(self.name, "neutral", 0.0, "No ticker provided.")
            
        try:
            news = get_news_data(ticker)
            
            if not news:
                return SetupSignal(self.name, "neutral", 0.0, "No recent news found.")
                
            analyzer = SentimentIntensityAnalyzer()
            
            total_compound = 0.0
            count = 0
            
            for item in news[:10]: # Look at top 10 recent articles
                title = item.get("title", "")
                if title:
                    score = analyzer.polarity_scores(title)
                    total_compound += score['compound']
                    count += 1
                    
            if count == 0:
                return SetupSignal(self.name, "neutral", 0.0, "No analyzable news titles found.")
                
            avg_sentiment = total_compound / count
            
            if avg_sentiment > 0.2:
                return SetupSignal(self.name, "bullish", 0.7, f"Highly positive news sentiment (Score: {avg_sentiment:.2f} across {count} articles).")
            elif avg_sentiment < -0.2:
                return SetupSignal(self.name, "bearish", 0.7, f"Highly negative news sentiment (Score: {avg_sentiment:.2f} across {count} articles).")
            else:
                return SetupSignal(self.name, "neutral", 0.4, f"Mixed or neutral news sentiment (Score: {avg_sentiment:.2f}).")
                
        except Exception as e:
            return SetupSignal(self.name, "neutral", 0.0, f"Error processing sentiment: {str(e)}")
