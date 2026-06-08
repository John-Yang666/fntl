import { C, IMG, bg, footer, iconLabel, kicker, panel, screenshot, smallSource, subcopy, text, title } from "./shared.mjs";

export async function slide06(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(ctx, slide);
  kicker(ctx, slide, "记录追溯");
  title(ctx, slide, "历史记录把复盘、归档和责任追溯放在同一入口。", 70, 76, 760, 74, { size: 40 });
  subcopy(ctx, slide, "历史告警、继电器动作和用户操作记录可按时间、线路、设备、告警码和确认状态筛选；导出文件用于交接班、事件复盘和现场归档。", 72, 154, 810, 54, { size: 18 });

  await screenshot(ctx, slide, IMG.records, 77, 248, 615, 362, { caption: "记录查询：多类记录集中筛选、分页和导出", fit: "contain" });

  const items = [
    ["CircleAlert", "历史告警", "看开始/结束时间、持续时长、确认状态。", C.red, C.redSoft],
    ["Activity", "继电器动作", "复核动作时间与现场处置是否一致。", C.amber, C.amberSoft],
    ["UserRoundCog", "用户操作", "保留账号、时间和操作痕迹。", C.cyan, C.cyanSoft],
    ["Download", "导出归档", "xlsx 适合统计，csv 适合大数据量。", C.green, C.greenSoft],
  ];
  for (let i = 0; i < items.length; i += 1) {
    const [icon, h, b, color, fill] = items[i];
    const y = 250 + i * 88;
    panel(ctx, slide, 760, y, 355, 68, { fill, border: "#D4D8DD" });
    await iconLabel(ctx, slide, icon, h, 782, y + 17, { iconSize: 22, color, w: 150, size: 17 });
    text(ctx, slide, b, 920, y + 16, 168, 36, { size: 13.5, color: C.muted, leading: 1.1 });
  }

  text(ctx, slide, "记录价值：历史告警、继电器动作和用户操作可统一查询、交接、归档和复盘。", 760, 626, 355, 38, {
    size: 15,
    color: C.ink,
    bold: true,
    leading: 1.16,
  });

  footer(ctx, slide, smallSource(), 6);
  return slide;
}
