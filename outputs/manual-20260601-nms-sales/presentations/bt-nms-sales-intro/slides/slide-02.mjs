import { C, bg, footer, kicker, panel, smallSource, subcopy, text, title } from "./shared.mjs";

export async function slide02(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(ctx, slide);
  kicker(ctx, slide, "客户痛点");
  title(ctx, slide, "分散巡检、告警滞后和记录断点，会放大现场运维风险。", 70, 78, 780, 90, { size: 39 });
  subcopy(ctx, slide, "系统通过统一控制台，将现场状态、告警处置和历史记录集中呈现，帮助日常值守从经验判断转为可视、可查、可复核的流程。", 72, 170, 850, 52);

  const rows = [
    ["状态看不全", "分散在不同设备、线路和后台页面，值守人员难以先看全局。", "统一拓扑总览，按设备/线路下钻到详情。", "全局可视，快速定位现场状态。"],
    ["告警闭环弱", "声音提醒、现场处理、确认记录容易脱节。", "当前告警、颜色提示、声音控制和确认记录联动。", "发现、确认、处置和复盘形成闭环。"],
    ["追溯成本高", "历史告警、继电器动作、用户操作分散，事后复盘慢。", "多类记录集中查询，支持筛选、分页和导出。", "运行数据可沉淀为长期运维资产。"],
  ];

  const x0 = 70;
  const widths = [260, 310, 310, 230];
  const heads = ["客户现场常见问题", "风险表现", "系统应对", "客户收益"];
  let x = x0;
  heads.forEach((h, i) => {
    panel(ctx, slide, x, 258, widths[i], 46, { fill: i === 0 ? C.tealDark : "#ECE7DD", border: C.line });
    text(ctx, slide, h, x + 16, 272, widths[i] - 32, 18, {
      size: 15,
      color: i === 0 ? C.white : C.ink,
      bold: true,
    });
    x += widths[i];
  });

  rows.forEach((row, r) => {
    let cx = x0;
    const y = 304 + r * 102;
    row.forEach((cell, c) => {
      const fill = c === 0 ? (r === 0 ? C.cyanSoft : r === 1 ? C.amberSoft : C.greenSoft) : C.white;
      panel(ctx, slide, cx, y, widths[c], 102, { fill, border: C.line });
      text(ctx, slide, cell, cx + 16, y + 18, widths[c] - 32, 62, {
        size: c === 0 ? 21 : 16,
        bold: c === 0,
        color: c === 0 ? C.ink : C.muted,
        leading: 1.15,
      });
      cx += widths[c];
    });
  });

  footer(ctx, slide, smallSource(), 2);
  return slide;
}
