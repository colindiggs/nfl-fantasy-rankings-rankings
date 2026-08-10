# Manual rankings inbox

Drop a CSV here to benchmark **any** ranker — a podcast's list, a Reddit post,
a paywalled site you transcribe, your own rankings. It gets scored exactly like
the scraped sources.

**Filename:** `{source}_{format}_{scope}.csv`

- `source` — lowercase slug, e.g. `harris-football` (shown on the site as "Harris Football")
- `format` — `standard`, `half_ppr`, or `ppr`
- `scope` — `predraft`, or `week01` … `week18` for weekly rankings

**Columns** (header row recommended): `rank,name,pos,team` — `pos`/`team` optional
but `pos` strongly recommended for exact matching.

```csv
rank,name,pos,team
1,Jahmyr Gibbs,RB,DET
2,Bijan Robinson,RB,ATL
```

Import happens automatically on every scheduled run, or manually:

```
cd scripts && python capture.py inbox
```

Processed files move to `processed/`. To submit a weekly board, drop it before
Thursday's games — scoring uses whatever was captured before kickoff.
