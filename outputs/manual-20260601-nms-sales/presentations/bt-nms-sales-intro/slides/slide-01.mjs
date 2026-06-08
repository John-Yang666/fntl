import { C, IMG, bg, chip, footer, line, panel, screenshot, subcopy, text } from "./shared.mjs";

export async function slide01(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(ctx, slide, { dark: true });

  ctx.addShape(slide, { x: 0, y: 0, w: ctx.W, h: ctx.H, fill: C.dark, line: line(C.dark, 0) });
  ctx.addShape(slide, { x: 812, y: 0, w: 468, h: ctx.H, fill: C.dark2, line: line(C.dark2, 0) });
  ctx.addShape(slide, { x: 78, y: 82, w: 52, h: 5, fill: C.cyan, line: line(C.cyan, 0) });
  text(ctx, slide, "FNTL-MS100", 78, 111, 260, 28, { size: 18, color: "#9ADCE3", bold: true });
  text(ctx, slide, "贝通云网管系统", 78, 152, 540, 74, { size: 58, color: C.white, bold: true, leading: 1.0 });
  subcopy(ctx, slide, "系统介绍｜集中监控、告警闭环、记录追溯、授权控制", 82, 246, 640, 58, {
    size: 22,
    color: "#D7EEF1",
  });

  const rail = [
    ["统一入口", "BT / SY 双系统"],
    ["实时可视", "拓扑 + 设备详情"],
    ["处置闭环", "告警确认 + 声音提醒"],
    ["可追溯", "记录导出 + 操作审计"],
  ];
  rail.forEach(([a, b], i) => {
    const x = 78 + i * 170;
    panel(ctx, slide, x, 380, 145, 96, { fill: "#16384A", border: "#31596A" });
    text(ctx, slide, a, x + 16, 399, 113, 24, { size: 20, color: C.white, bold: true });
    text(ctx, slide, b, x + 16, 431, 113, 24, { size: 13, color: "#A9CAD1" });
  });

  await screenshot(ctx, slide, IMG.monitor, 750, 92, 440, 286, { pad: 6, caption: "", fit: "contain" });
  await screenshot(ctx, slide, IMG.alerts, 830, 342, 360, 224, { pad: 6, caption: "", fit: "contain" });
  chip(ctx, slide, "从状态发现到事件追溯的一套值守工作台", 800, 598, 360, {
    fill: "#0D2232",
    border: "#3C7381",
    color: "#CDEFF3",
  });

  text(ctx, slide, "产品介绍｜2026-06-01", 78, 648, 360, 24, { size: 13, color: "#9AB8C0" });
  footer(ctx, slide, "FNTL-MS100 贝通云网管系统 | 产品介绍", 1);
  return slide;
}
