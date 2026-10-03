# Feature: Sector Dispersion Analysis (セクター分散分析)

| Item | Details |
|------|---------|
| Document Type | Feature Specification |
| Project | uptrend-dashboard |
| Created | 2026-04-11 |
| Status | Draft |
| Priority | High |
| Prerequisite | v4.3 (current) |

---

## 1. Background & Motivation

Sector Comparison チャート（10MA）の11セクターラインには、**密集（収束）と拡散（発散）のサイクル**が存在する。このパターンにはマーケットの先行シグナルとしての優位性がある。

### 分析結果サマリー（2024-07〜2026-03、N=387日）

セクター10MA Uptrend Ratioの断面標準偏差（σ）を「分散指標（Dispersion）」として計算。

#### 分散レジーム別の市場フォワードリターン

| 条件 | N | 5d後 | 10d後 | 20d後 |
|------|---|------|-------|-------|
| **低分散 + 低水準** (σ<p25 & mean<20%) | 90 | +0.018 | +0.045 | **+0.073** (勝率73%) |
| 低分散（全般、σ<p25） | 97 | +0.018 | +0.045 | +0.068 |
| ベースライン（全期間） | 387 | -0.003 | -0.003 | +0.000 |
| 高分散（全般、σ>p75） | 97 | -0.006 | -0.010 | -0.018 |
| **極端高分散**（σ>p90） | 39 | **-0.027** | -0.025 | -0.001 |

#### 収束後に最も上昇するセクター（10d後）

| Sector | Mean Change | Win Rate |
|--------|-------------|----------|
| Financial | +0.062 | 74.2% |
| Industrials | +0.052 | 69.1% |
| Consumer Cyclical | +0.047 | 70.1% |
| Basic Materials | +0.044 | 70.1% |

#### 高分散期にプラスを維持するセクター

| Sector | Mean 10d Change | Win Rate |
|--------|-----------------|----------|
| Energy | +0.052 | 73.6% |
| Utilities | +0.029 | 69.0% |
| 他の全セクター | マイナス | <50% |

#### 実例: 2025年3月

- 2025-03-18: σ=0.037（データ全期間の最小値）、平均Ratio≒10%
- 全セクターが一斉に沈んだ「キャピチュレーション」状態
- その後マーケットは回復へ

---

## 2. Feature Overview

### 2.1 新規計算: Dispersion Indicator

`indicator_calculator.py` に以下を追加:

```python
def calculate_sector_dispersion(sector_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Calculate cross-sectional dispersion of sector uptrend ratios.

    Parameters:
        sector_data: Dict mapping sector keys to DataFrames with 'ma_10' column

    Returns:
        DataFrame with columns:
        - date: index
        - dispersion: cross-sectional std dev of 11 sectors' ma_10
        - mean_ratio: cross-sectional mean of 11 sectors' ma_10
        - range: max - min across sectors
        - dispersion_ma10: 10-day MA of dispersion (smoothed)
        - dispersion_velocity: 3-day rate of change of dispersion
        - regime: 'converged' | 'normal' | 'diverged'
        - level_regime: 'low' | 'mid' | 'high' (mean_ratio based)
    """
```

#### Regime Classification

Expanding window percentile を使用（ルックアヘッドバイアス回避）:

| Regime | Condition |
|--------|-----------|
| `converged` | dispersion < expanding 25th percentile |
| `normal` | between 25th and 75th |
| `diverged` | dispersion > expanding 75th percentile |

##### Regime Stabilization (Causal Confirmation, v5.1)

Raw regime labels are noise-reduced by `_confirm_regime(regime, DISPERSION_MIN_REGIME_DAYS)`, a
left-to-right sequential state machine (replaces the prior lookahead `_stabilize_regime`):

- A regime change is confirmed only on the `DISPERSION_MIN_REGIME_DAYS`-th consecutive valid day of the
  new regime; before that, rows keep the previous confirmed regime (short blips are absorbed as noise).
- **No lookahead / prefix-invariant**: each row's label depends only on observations up to that row, so
  appending future history never relabels an earlier row (Issue #4 fix).
- **Missing observations**: a NaN day resets the in-progress candidate run, is emitted as NaN, and does not
  extend a run — a transition needs `min_days` consecutive valid days. (Old behavior treated a
  NaN-interrupted run as contiguous because it operated on `dropna()`; this is an intentional, conservative
  change.)
- **Initial regime**: the first non-NaN classification becomes the baseline immediately and is never
  relabeled.
- Forward-return / sector-edge events use the composite `(regime, level_regime)` transition, which now
  occurs on the confirmation date (see Section 2.5).

Level regime (mean_ratio):

| Level | Condition |
|-------|-----------|
| `low` | mean_ratio < 0.20 |
| `mid` | 0.20 <= mean_ratio < 0.35 |
| `high` | mean_ratio >= 0.35 |

#### Signal Definitions

| Signal ID | Name | Condition |
|-----------|------|-----------|
| `CAPITULATION` | キャピチュレーション | regime=converged AND level=low |
| `DIVERGENCE_WARNING` | 分散拡大警告 | regime=diverged |
| `BREAKOUT_VELOCITY` | 収束脱出 | dispersion_velocity > p90 AND dispersion < median |

各シグナルの「歴史的傾向」テキスト（フォワードリターン、勝率、リーダーセクター）は
すべて `calculate_forward_stats()` から動的に算出する（Section 2.5 参照）。

### 2.2 新規ページ: `6_Dispersion_Monitor.py`

#### レイアウト

```
┌─────────────────────────────────────────────────┐
│ Sector Dispersion Monitor                       │
├────────────────────┬────────────────────────────┤
│ [Sidebar]          │ [Main Area]                │
│ Date range         │                            │
│ Regime filter      │ 1. Signal Banner           │
│                    │    Active signals with      │
│                    │    color-coded badges       │
│                    │                            │
│                    │ 2. Dispersion Chart         │
│                    │    - Dispersion (σ) line    │
│                    │    - Mean ratio line        │
│                    │    - Regime bands (bg color)│
│                    │    - p25/p75 threshold lines│
│                    │                            │
│                    │ 3. Regime Timeline          │
│                    │    Horizontal bar showing   │
│                    │    regime transitions       │
│                    │                            │
│                    │ 4. Sector Ranking Table     │
│                    │    Current sector order by  │
│                    │    ratio, with regime-aware │
│                    │    recommendations          │
│                    │                            │
│                    │ 5. Historical Stats         │
│                    │    Forward returns by regime│
└────────────────────┴────────────────────────────┘
```

#### 1. Signal Banner

現在アクティブなシグナルをカード形式で表示。
**歴史的傾向のテキストはすべて `calculate_forward_stats()` の戻り値から動的生成する。**

```
🔴 CAPITULATION ACTIVE — 全セクター収束・低水準 (σ=0.042, mean=12%)
   歴史的傾向: 20日後 +{fwd_20d}pts (勝率{win_rate_20d}) | リーダー候補: {top_sectors}
```

```
🟡 DIVERGENCE WARNING — セクター分散拡大中 (σ=0.135)
   歴史的傾向: 10日後 {fwd_10d}pts (勝率{win_rate_10d}) | ディフェンシブ: {survivor_sectors}
```

シグナルなしの場合: `🟢 NORMAL — セクター分散は通常範囲`

#### 2. Dispersion Chart (Plotly)

- **Primary Y-axis (left)**: Dispersion (σ) — line chart
- **Secondary Y-axis (right)**: Mean Ratio — dotted line
- **Background bands**: Regime ごとに色分け
  - Converged: 薄緑 (rgba(0,255,0,0.05))
  - Diverged: 薄赤 (rgba(255,0,0,0.05))
- **Horizontal threshold lines**: p25, p75 (dashed)
- **Annotations**: Regime transition points

#### 3. Regime Timeline

水平棒グラフで regime 遷移を可視化:

```
2024-08 ████████ CONVERGED (mean=0.21)
2024-09 ██████████████ NORMAL (mean=0.33)
2024-09 ████ DIVERGED (mean=0.27)
...
```

#### 4. Sector Ranking Table

現在の regime に応じたセクターランキング。
**ソート順・Historical Edge 列の値はすべて `calculate_forward_stats()` から動的に取得する。**

- **Converged regime**: 収束後の10d forward change が大きいセクター順
- **Diverged regime**: 高分散期の10d forward change がプラスのセクター順
- **Normal regime**: 現在のRatio順

Columns: `Sector | Current Ratio | 10MA | Trend | Hist. 10d Fwd | Hist. Win Rate`

#### 5. Historical Stats (Expander)

折りたたみ式で regime 別の統計テーブルを表示。
**すべて `calculate_forward_stats()` から動的計算。データが蓄積されるほど統計の信頼性が向上する。**

- Forward return distribution (5d/10d/20d): mean, median
- Win rate (positive forward change の割合)
- サンプル数 (N)
- 最終更新日（データの最新日付）

### 2.5 Dynamic Stats Calculation: `calculate_forward_stats()`

`indicator_calculator.py` に追加。全てのシグナルバナー、セクターランキング、Historical Stats
の数値データソースとなる関数。

```python
def calculate_forward_stats(
    dispersion_df: pd.DataFrame,
    sector_data: Dict[str, pd.DataFrame],
    market_data: pd.DataFrame,
    horizons: Tuple[int, ...] = (5, 10, 20),
) -> ForwardStats:
    """
    Calculate forward returns by regime, dynamically from all available data.

    Uses only past data at each point (no lookahead).

    Parameters:
        dispersion_df: Output of calculate_sector_dispersion()
        sector_data: Dict of sector DataFrames with 'ma_10'
        market_data: 'all' worksheet DataFrame with 'ma_10'
        horizons: Forward return horizons in days

    Returns:
        ForwardStats dataclass containing:
        - market_stats: Dict[regime_name, RegimeStats]
          - RegimeStats: n, fwd_mean, fwd_median, win_rate (per horizon)
        - sector_stats: Dict[regime_name, Dict[sector_key, SectorRegimeStats]]
          - SectorRegimeStats: fwd_mean, win_rate (per horizon)
        - leader_sectors: Dict[regime_name, List[str]]
          Top 3 sectors by fwd_mean for each regime
        - survivor_sectors: Dict[regime_name, List[str]]
          Sectors with positive fwd_mean during that regime
        - data_range: Tuple[str, str] (start_date, end_date)
        - total_days: int
    """
```

#### Return Type Definitions

```python
@dataclass
class RegimeStats:
    n: int                          # Sample count
    fwd_mean: Dict[int, float]     # {5: 0.018, 10: 0.045, 20: 0.073}
    fwd_median: Dict[int, float]
    win_rate: Dict[int, float]     # {5: 0.65, 10: 0.71, 20: 0.73}

@dataclass
class SectorRegimeStats:
    fwd_mean: Dict[int, float]
    win_rate: Dict[int, float]

@dataclass
class ForwardStats:
    market_stats: Dict[str, RegimeStats]     # 'converged_low', 'converged', 'diverged', 'baseline'
    sector_stats: Dict[str, Dict[str, SectorRegimeStats]]
    leader_sectors: Dict[str, List[str]]     # regime -> top 3 sector keys
    survivor_sectors: Dict[str, List[str]]   # regime -> positive-fwd sectors
    data_range: Tuple[str, str]
    total_days: int
```

#### Caching Strategy

- `@st.cache_data(ttl=3600)` で1時間キャッシュ（既存のセクターデータと同じTTL）
- ページロード時に1回計算、Signal Banner / Sector Ranking / Historical Stats で共有

### 2.3 Sector Comparison ページへの追加

既存の `2_Sector_Comparison.py` に以下を追加:

- **Dispersion gauge**: サイドバーに現在のσと regime バッジを表示
- **Link**: 「詳細分析 → Dispersion Monitor」のリンク

### 2.4 CSV Export 拡張

`export_csv.py` に追加:

- `data/sector_dispersion.csv`: date, dispersion, mean_ratio, range, regime, level_regime
- GitHub Actions の export ステップに追加

---

## 3. Constants (`src/constants.py`)

```python
# Dispersion thresholds (expanding window percentiles are primary,
# these are fallback for insufficient history)
DISPERSION_CONVERGED_FALLBACK = 0.066  # ~p25 from historical data
DISPERSION_DIVERGED_FALLBACK = 0.110   # ~p75 from historical data

# Mean ratio level thresholds
MEAN_RATIO_LOW = 0.20
MEAN_RATIO_HIGH = 0.35

# Dispersion velocity — absolute diff, NOT pct_change
# Rationale: σ range is narrow (0.037-0.147), pct_change overreacts at low σ
DISPERSION_VELOCITY_WINDOW = 3  # dispersion.diff(3): absolute change over 3 days

# Minimum history for expanding window percentile
DISPERSION_MIN_HISTORY = 60  # days before using expanding percentile
```

---

## 4. Data Flow

```
cached_load_sector_data() — existing function, returns Dict[str, DataFrame]
    ↓
calculate_sector_dispersion(sector_data) — NEW
    ↓ returns DataFrame with dispersion, regime, signals
6_Dispersion_Monitor.py
    ↓
build_dispersion_chart() — NEW in chart_builder.py
build_regime_timeline_chart() — NEW in chart_builder.py
build_sector_ranking_table() — NEW in data_processor.py
```

---

## 5. Implementation Plan

### Phase 1: Core Calculation (indicator_calculator.py)

1. `calculate_sector_dispersion()` 実装
2. Regime classification ロジック
3. Signal detection ロジック
4. テスト: 合成データで全 regime / signal パターンをカバー

### Phase 2: Chart & UI Components (chart_builder.py, data_processor.py)

1. `build_dispersion_chart()` — dual-axis, regime bands
2. `build_regime_timeline_chart()` — horizontal bar
3. `build_sector_ranking_table()` — regime-aware ranking
4. テスト: チャート生成、テーブル生成

### Phase 3: Page Assembly (pages/6_Dispersion_Monitor.py)

1. ページ構築（上記レイアウト）
2. Signal banner ロジック
3. サイドバーフィルター
4. Sector Comparison ページへの小改修

### Phase 4: Export & Integration

1. CSV export 拡張
2. GitHub Actions 更新
3. design.md 更新（v5.0）
4. レジーム確定の因果化対応（v5.1, Issue #4）

---

## 6. Test Plan

| Category | Test Cases | Location |
|----------|-----------|----------|
| Dispersion calculation | Empty data, single sector, all sectors equal (σ=0), normal data | `tests/test_indicator_calculator.py` |
| Regime classification | Below p25, above p75, between, insufficient history (fallback) | `tests/test_indicator_calculator.py` |
| Regime stabilization (v5.1) | Causal `_confirm_regime`: short blip absorbed, confirmation on min_days-th day, NaN resets candidate, initial baseline, prefix-invariance (deterministic + randomized) | `tests/test_indicator_calculator.py` |
| Regime prefix-invariance (v5.1) | `calculate_sector_dispersion()` regime column identical over shared dates when truncated vs full | `tests/test_indicator_calculator.py` |
| Forward event date (v5.1) | Forward-return event detected on confirmation date, and no event for an unconfirmed blip | `tests/test_indicator_calculator.py` |
| Signal detection | CAPITULATION (low+converged), DIVERGENCE_WARNING, BREAKOUT_VELOCITY, no signal | `tests/test_indicator_calculator.py` |
| Forward stats | Regime-wise fwd returns match manual calc, leader/survivor ranking, empty data, single regime | `tests/test_indicator_calculator.py` |
| Expanding window | Verify no future data leakage, min history guard | `tests/test_indicator_calculator.py` |
| Chart building | Dispersion chart traces, regime bands, timeline chart | `tests/test_chart_builder.py` |
| Sector ranking | Correct sort order per regime, table columns | `tests/test_data_processor.py` |
| CSV export | New file generated, correct columns, data integrity | `tests/test_export_csv.py` |
| Page integration | Page loads without error, signal banner renders | `tests/test_pages.py` |

---

## 7. Limitations & Future Work

### Known Limitations

- **Sample size**: 約387日分のデータ（2024-07〜2026-03）。複数のフルマーケットサイクルでの検証が必要
- **Expanding window**: 初期60日間は固定フォールバック閾値を使用
- **Forward return**: Uptrend Ratio の変化であり、実際の株価リターンではない

### Future Enhancements

- **Backtesting integration**: trade-edge-finder と連携して実際のリターンで検証
- **Industry-level dispersion**: 149 industry で同様の分析（セクター内の収束/発散）
- **Alert system**: CAPITULATION シグナル発火時の通知
- **Correlation with VIX/Put-Call**: 外部指標との相関分析
