import { C, IMG, bg, footer, iconLabel, kicker, panel, screenshot, smallSource, subcopy, text, title } from "./shared.mjs";

export async function slide04(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(ctx, slide);
  kicker(ctx, slide, "实时监控");
  title(ctx, slide, "拓扑总览：先看全局再下钻", 70, 76, 510, 56, { size: 38 });
  subcopy(ctx, slide, "绿色、黄色、红色和灰色状态帮助快速定位设备与链路异常；左侧设备列表和详情页承接具体状态、邻站关系和单板信息。", 72, 152, 660, 54, { size: 18.5 });

  await screenshot(ctx, slide, IMG.monitor, 600, 82, 565, 354, { caption: "设备监控总览：拓扑、设备列表和全局指标", fit: "contain" });
  await screenshot(ctx, slide, IMG.normalDevice, 80, 266, 440, 275, { caption: "设备详情：邻站、网管板、方向状态、单板状态", fit: "contain" });

  const callouts = [
    ["Network", "拓扑颜色先提示状态", "先看颜色变化，再打开设备详情确认含义。"],
    ["PanelTop", "单台设备可下钻", "设备详情显示邻站关系、备注和方向状态。"],
    ["Volume2", "声音开关适合值班席", "可试音、暂停当前提示音，但不替代告警处理。"],
  ];
  for (let i = 0; i < callouts.length; i += 1) {
    const [icon, h, b] = callouts[i];
    const x = 580 + i * 205;
    panel(ctx, slide, x, 504, 180, 96, { fill: i === 1 ? C.amberSoft : C.white, border: C.line });
    await iconLabel(ctx, slide, icon, h, x + 16, 521, { iconSize: 21, w: 132, size: 15.5, color: i === 1 ? C.amber : C.cyan });
    text(ctx, slide, b, x + 16, 552, 148, 32, { size: 12.5, color: C.muted, leading: 1.1 });
  }

  footer(ctx, slide, smallSource(), 4);
  return slide;
}
