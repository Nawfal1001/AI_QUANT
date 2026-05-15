from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Optional
import pandas as pd

from middleware.auth import get_current_user
from services.position_sizing import kelly, monte_carlo, dar, optimal_position
from services.bayesian_engine import bayesian_vote, get_likelihood_table
from services.advanced_indicators import optimal_trailing_stop
from services.trade_optimizer import (
    mtf_confluence, order_book_analysis, mean_reversion,
    portfolio_risk_check, news_halt_check, get_config, save_config, run_optimization,
)

router = APIRouter()


class Kelly(BaseModel):
    win_rate: float; avg_win_pct: float; avg_loss_pct: float; fraction: float = 0.5

class MC(BaseModel):
    trade_history: List[float]; capital: float; proposed_position_pct: float; max_acceptable_drawdown: float = 20.0

class DAR(BaseModel):
    equity_curve: List[float]; confidence: float = 0.95

class Opt(BaseModel):
    ticker: str; asset_type: str = "stock"; signal: str; capital: float
    win_rate: float; avg_win_pct: float; avg_loss_pct: float
    regime: str = "RANGING"; trade_history: List[float] = []; equity_curve: List[float] = []

class Trail(BaseModel):
    entry_price: float; current_price: float; atr: float
    elapsed_bars: int; max_bars: int; side: str = "long"; k: float = 2.0

class Bayes(BaseModel):
    indicators: List[dict]; regime: str = "RANGING"; ai_score: int = 0

class MTF(BaseModel):
    ticker: str; asset_type: str = "stock"; mode: str = "swing"

class PR(BaseModel):
    new_trade_risk_pct: float; open_positions: List[dict] = []

class Optimize(BaseModel):
    ticker: str; asset_type: str; base_signal: str; base_confidence: int
    regime: str = "RANGING"; closes: Optional[List[float]] = None
    open_positions: List[dict] = []; risk_pct: float = 2.0


@router.post("/kelly")
async def do_kelly(r: Kelly, user=Depends(get_current_user)):
    return kelly(r.win_rate, r.avg_win_pct, r.avg_loss_pct, r.fraction)


@router.post("/monte-carlo")
async def do_mc(r: MC, user=Depends(get_current_user)):
    return monte_carlo(r.trade_history, r.capital, r.proposed_position_pct, r.max_acceptable_drawdown)


@router.post("/dar")
async def do_dar(r: DAR, user=Depends(get_current_user)):
    return dar(r.equity_curve, r.confidence)


@router.post("/optimal")
async def do_opt(r: Opt, user=Depends(get_current_user)):
    return await optimal_position(
        r.ticker, r.asset_type, r.signal, r.capital,
        r.win_rate, r.avg_win_pct, r.avg_loss_pct,
        r.regime, r.trade_history, r.equity_curve,
    )


@router.post("/trailing-stop")
async def do_trail(r: Trail, user=Depends(get_current_user)):
    return optimal_trailing_stop(r.entry_price, r.current_price, r.atr, r.elapsed_bars, r.max_bars, r.side, r.k)


@router.post("/bayesian/vote")
async def do_bayes(r: Bayes, user=Depends(get_current_user)):
    return await bayesian_vote(r.indicators, r.regime, r.ai_score)


@router.get("/bayesian/likelihoods")
async def likelihoods(user=Depends(get_current_user)):
    return await get_likelihood_table()


@router.post("/mtf")
async def do_mtf(r: MTF, user=Depends(get_current_user)):
    return await mtf_confluence(r.ticker, r.asset_type, r.mode)


@router.get("/orderbook/{ticker}")
async def ob(ticker: str, user=Depends(get_current_user)):
    return await order_book_analysis(ticker.upper())


@router.post("/portfolio-risk")
async def pr(r: PR, user=Depends(get_current_user)):
    return await portfolio_risk_check(r.new_trade_risk_pct, r.open_positions)


@router.get("/news-halt/{ticker}")
async def nh(ticker: str, asset_type: str = "stock", user=Depends(get_current_user)):
    return await news_halt_check(ticker.upper(), asset_type)


@router.get("/config")
async def cfg(user=Depends(get_current_user)):
    return await get_config()


@router.post("/config")
async def save_cfg(c: dict, user=Depends(get_current_user)):
    return await save_config(c)


@router.post("/optimize")
async def do_optimize(r: Optimize, user=Depends(get_current_user)):
    cl = pd.Series(r.closes) if r.closes else None
    return await run_optimization(
        r.ticker, r.asset_type, r.base_signal, r.base_confidence,
        cl, r.regime, r.open_positions, r.risk_pct,
    )
