from fastapi import APIRouter
import feedparser
router=APIRouter()
@router.get("/{ticker}")
async def sentiment(ticker:str,asset_type:str="stock"):
    try:
        feed=feedparser.parse(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US")
        headlines=[e.get("title","") for e in feed.entries[:10]]; score=0
        pos=["surge","gain","bull","beat","rise","growth","profit","strong","up"]
        neg=["drop","fall","bear","miss","loss","weak","crash","concern","down"]
        for h in headlines:
            hl=h.lower()
            for w in pos:
                if w in hl: score+=1
            for w in neg:
                if w in hl: score-=1
        return {"ticker":ticker,"overall":"bullish" if score>2 else "bearish" if score<-2 else "neutral","score":score,"headlines":headlines[:5]}
    except Exception as e: return {"ticker":ticker,"overall":"neutral","score":0,"error":str(e)}
