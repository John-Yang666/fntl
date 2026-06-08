import { C, IMG, bg, footer, kicker, line, numberedStep, panel, screenshot, smallSource, subcopy, text, title } from "./shared.mjs";

export async function slide05(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(ctx, slide);
  kicker(ctx, slide, "告警闭环");
  title(ctx, slide, "告警提醒到确认，形成处理闭环", 70, 76, 560, 58, { size: 37 });
  subcopy(ctx, slide, "当前告警确认表示人员已知晓，系统会把声音提醒、颜色提示、告警明细、确认记录和后续复盘连接起来。", 72, 148, 560, 64, { size: 18 });

  await screenshot(ctx, slide, IMG.alerts, 690, 78, 500, 312, { caption: "当前告警列表：按系统、设备、告警含义筛选并确认", fit: "contain" });

  await numberedStep(ctx, slide, 1, "BellRing", "出现提醒", "页面顶部、拓扑颜色和入口数量同时提示。", 80, 260, 260, { color: C.red, fill: C.redSoft });
  await numberedStep(ctx, slide, 2, "UserCheck", "人员确认", "值守人员核对设备、告警码和起始时间。", 360, 260, 260, { color: C.amber, fill: C.amberSoft });
  await numberedStep(ctx, slide, 3, "ClipboardList", "现场处置", "按现场流程处理，记录设备名称和结果。", 80, 396, 260, { color: C.cyan, fill: C.cyanSoft });
  await numberedStep(ctx, slide, 4, "FileClock", "记录复盘", "新的告警或状态变化会再次提醒并留痕。", 360, 396, 260, { color: C.green, fill: C.greenSoft });

  ctx.addShape(slide, { x: 340, y: 309, w: 20, h: 3, fill: C.line, line: line(C.line, 0) });
  ctx.addShape(slide, { x: 205, y: 370, w: 3, h: 26, fill: C.line, line: line(C.line, 0) });
  ctx.addShape(slide, { x: 340, y: 445, w: 20, h: 3, fill: C.line, line: line(C.line, 0) });

  panel(ctx, slide, 710, 450, 440, 104, { fill: C.white, border: "#C9D0D8" });
  text(ctx, slide, "闭环价值", 734, 474, 90, 22, { size: 18, bold: true, color: C.tealDark });
  text(ctx, slide, "系统不只是弹出告警，还把告警声音、设备颜色、人员确认、历史记录和导出复盘串成闭环。", 834, 468, 276, 52, { size: 17, color: C.ink, leading: 1.16 });

  footer(ctx, slide, smallSource(), 5);
  return slide;
}
