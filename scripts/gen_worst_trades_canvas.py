"""Generate canvas for worst earnings_forecast trades."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

CSV = Path(r"d:/cursor_space/jx/data/factors/earnings_forecast_worst_trades.csv")
CANVAS = Path(
    r"C:/Users/GaoZX/.cursor/projects/d-cursor-space-jx/canvases/earnings-forecast-worst-trades.canvas.tsx"
)


def main() -> None:
    df = pd.read_csv(CSV, encoding="utf-8-sig")
    top = df.head(40)
    rows: list[list[str]] = []
    tones: list[str] = []
    for _, r in top.iterrows():
        loss = float(str(r["亏损幅度"]).replace("%", ""))
        tones.append("danger" if loss <= -18 else "warning")
        rows.append(
            [
                str(r["亏损幅度"]),
                str(r["代码"]),
                str(r["公告日"]),
                str(r["买入日"]),
                str(r["卖出日"]),
                str(r["买入仓位"]),
                str(int(r["同时持仓数"])),
                str(r["公告前涨幅"]),
                str(r["买入价"]),
                str(r["入场路径"]),
                str(r["卖出原因"]),
                str(r["备注"]),
            ]
        )

    data_lit = json.dumps(rows, ensure_ascii=False)
    tones_lit = json.dumps(tones, ensure_ascii=False)
    content = f"""import {{
  Card,
  CardBody,
  CardHeader,
  Callout,
  H1,
  Stack,
  Stat,
  Grid,
  Table,
  Text,
}} from "cursor/canvas";

const ROWS: string[][] = {data_lit};
const TONES = {tones_lit} as Array<"danger" | "warning" | undefined>;

export default function EarningsForecastWorstTrades() {{
  return (
    <Stack gap={{20}}>
      <H1>业绩预告因子 · 亏损最大成交</H1>
      <Text tone="secondary" size="small">
        组合已接受笔（最多8仓等权）· 按单笔亏损从大到小 · 2018-01 至 2026-07 · 完整表见 data/factors/earnings_forecast_worst_trades.csv
      </Text>
      <Grid columns={{3}} gap={{12}}>
        <Stat value={{ROWS[0][0]}} label="最大单笔亏损" tone="danger" />
        <Stat value="40" label="本表展示笔数" />
        <Stat value="600" label="组合接受总笔数" />
      </Grid>
      <Callout tone="info" title="字段说明">
        买入仓位 = 开仓后 1/同时持仓数；公告前涨幅 = 公告日前20个交易日涨幅；价格为后复权。
      </Callout>
      <Card>
        <CardHeader>亏损 Top 40</CardHeader>
        <CardBody style={{{{ padding: 0 }}}}>
          <Table
            stickyHeader
            striped
            headers={{[
              "亏损",
              "代码",
              "公告日",
              "买入日",
              "卖出日",
              "买入仓位",
              "持仓数",
              "公告前涨幅",
              "买入价",
              "路径",
              "卖出原因",
              "备注",
            ]}}
            rows={{ROWS}}
            rowTone={{TONES}}
            columnAlign={{[
              "right",
              "left",
              "left",
              "left",
              "left",
              "right",
              "right",
              "right",
              "right",
              "left",
              "left",
              "left",
            ]}}
          />
        </CardBody>
      </Card>
    </Stack>
  );
}}
"""
    CANVAS.write_text(content, encoding="utf-8")
    print(f"wrote {CANVAS}")


if __name__ == "__main__":
    main()
