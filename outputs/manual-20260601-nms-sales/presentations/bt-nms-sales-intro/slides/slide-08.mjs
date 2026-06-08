import { C, IMG, bg, footer, kicker, panel, screenshot, smallSource, subcopy, text, title } from "./shared.mjs";

export async function slide08(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(ctx, slide);
  kicker(ctx, slide, "客户侧运维");
  title(ctx, slide, "管理员可维护参数、资料和后台台账，提升客户侧维护能力。", 70, 76, 850, 74, { size: 40 });
  subcopy(ctx, slide, "客户管理员可按权限维护运行参数、FAQ/文件资料和后台基础数据；高风险动作保留复核要求和操作记录。", 72, 154, 1040, 44, { size: 18.5 });

  const cards = [
    [IMG.settings, "系统设置", "维护告警、声音、导出、清理和页面范围等运行参数。"],
    [IMG.help, "帮助与资料管理", "发布 FAQ、操作说明、模板文件和维护资料。"],
    [IMG.adminList, "后台台账维护", "维护设备、线路、用户和记录筛选导出入口。"],
  ];
  for (let i = 0; i < cards.length; i += 1) {
    const [img, h, b] = cards[i];
    const x = 72 + i * 374;
    await screenshot(ctx, slide, img, x, 260, 330, 206, { fit: "contain" });
    panel(ctx, slide, x, 492, 330, 100, { fill: i === 1 ? C.amberSoft : C.white, border: C.line });
    text(ctx, slide, h, x + 20, 515, 280, 24, { size: 22, color: C.ink, bold: true });
    text(ctx, slide, b, x + 20, 548, 286, 30, { size: 14, color: C.muted, leading: 1.12 });
  }

  text(ctx, slide, "运维价值：长期值守、资料交接和参数维护可沉淀在系统中，减少依赖个人电脑或纸面记录。", 76, 626, 1040, 34, {
    size: 16,
    color: C.ink,
    bold: true,
  });

  footer(ctx, slide, smallSource(), 8);
  return slide;
}
