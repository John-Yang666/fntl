import { C, IMG, bg, chip, footer, iconLabel, kicker, line, panel, screenshot, smallSource, subcopy, text, title } from "./shared.mjs";

export async function slide10(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(ctx, slide, { dark: true });
  kicker(ctx, slide, "建设路径", 70, 48, "#9ADCE3");
  title(ctx, slide, "从可视化监控切入，逐步形成告警闭环和运维数据资产。", 70, 82, 810, 92, {
    size: 43,
    color: C.white,
    leading: 1.08,
  });
  subcopy(ctx, slide, "面向长期值守、多设备接入、告警处置留痕和运行记录归档的现场管理场景。", 72, 184, 690, 34, {
    size: 20,
    color: "#D7EEF1",
  });

  const fits = [
    ["Network", "多线路 / 多车间", "需要统一查看设备、线路和邻站关系。"],
    ["BellRing", "告警响应要求高", "需要声音提醒、颜色提示和确认记录。"],
    ["Archive", "运行记录要归档", "需要历史告警、动作和操作记录导出。"],
    ["ShieldCheck", "控制动作需授权", "需要验证、复核和审计边界。"],
  ];
  for (let i = 0; i < fits.length; i += 1) {
    const [icon, h, b] = fits[i];
    const x = 76 + (i % 2) * 330;
    const y = 270 + Math.floor(i / 2) * 122;
    panel(ctx, slide, x, y, 286, 86, { fill: "#153548", border: "#31596A" });
    await iconLabel(ctx, slide, icon, h, x + 18, y + 20, { iconSize: 24, color: i === 1 ? C.amber : "#65D7E0", textColor: C.white, w: 190, size: 17 });
    text(ctx, slide, b, x + 56, y + 50, 198, 24, { size: 12.5, color: "#B7D4DB", leading: 1.12 });
  }

  panel(ctx, slide, 760, 258, 390, 292, { fill: C.white, border: "#C8D1D8" });
  text(ctx, slide, "建设建议", 790, 286, 220, 30, { size: 25, color: C.tealDark, bold: true });
  const path = [
    ["01", "接入评估", "梳理设备、线路、账号和现场网络条件。"],
    ["02", "分阶段上线", "先接入重点线路/车间，验证设备数据和告警规则。"],
    ["03", "流程固化", "形成告警确认、记录导出、FAQ 和资料发布流程。"],
  ];
  path.forEach(([n, h, b], i) => {
    const y = 342 + i * 62;
    ctx.addShape(slide, { x: 795, y: y + 3, w: 32, h: 32, geometry: "ellipse", fill: i === 0 ? C.cyan : i === 1 ? C.amber : C.green, line: line("#00000000", 0) });
    text(ctx, slide, n, 795, y + 10, 32, 14, { size: 10.5, color: C.white, bold: true, align: "center" });
    text(ctx, slide, h, 846, y, 160, 22, { size: 17, color: C.ink, bold: true });
    text(ctx, slide, b, 846, y + 25, 236, 24, { size: 12.8, color: C.muted });
    if (i < 2) ctx.addShape(slide, { x: 810, y: y + 39, w: 2, h: 22, fill: C.line, line: line(C.line, 0) });
  });

  await screenshot(ctx, slide, IMG.monitor, 760, 574, 180, 82, { pad: 4, fit: "cover" });
  await screenshot(ctx, slide, IMG.alerts, 956, 574, 180, 82, { pad: 4, fit: "cover" });
  chip(ctx, slide, "建设目标：先实现现场可视，再形成处置闭环和运维沉淀。", 76, 574, 560, {
    fill: "#0D2232",
    border: "#3C7381",
    color: "#CDEFF3",
    h: 42,
    size: 17,
  });

  footer(ctx, slide, smallSource(), 10);
  return slide;
}
