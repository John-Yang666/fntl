export const ASSET_ROOT = "/Users/yangzijiang/BT_NMS/outputs/manual-20260601-nms-sales/presentations/bt-nms-sales-intro/assets/manual_media";

export const IMG = {
  login: `${ASSET_ROOT}/image1.png`,
  monitor: `${ASSET_ROOT}/image2.png`,
  normalDevice: `${ASSET_ROOT}/image6.png`,
  faultDevice: `${ASSET_ROOT}/image7.png`,
  alerts: `${ASSET_ROOT}/image8.png`,
  records: `${ASSET_ROOT}/image9.png`,
  command: `${ASSET_ROOT}/image12.png`,
  commandPanel: "/Users/yangzijiang/BT_NMS/outputs/manual-20260601-nms-sales/presentations/bt-nms-sales-intro/assets/remote_command_panel_crop.png",
  settings: `${ASSET_ROOT}/image13.png`,
  help: `${ASSET_ROOT}/image14.png`,
  adminList: `${ASSET_ROOT}/image15.png`,
  adminEdit: `${ASSET_ROOT}/image16.png`,
  syAdmin: `${ASSET_ROOT}/image20.png`,
};

export const C = {
  paper: "#F7F4EE",
  paper2: "#FBFAF6",
  ink: "#172033",
  muted: "#667085",
  faint: "#E5E0D6",
  line: "#D7D3C8",
  tealDark: "#0D3B4A",
  teal: "#127986",
  cyan: "#11A6B3",
  cyanSoft: "#DDF5F7",
  amber: "#F2A33A",
  amberSoft: "#FFF0D6",
  red: "#D9493F",
  redSoft: "#FCE7E4",
  green: "#2F9E5E",
  greenSoft: "#E2F5EA",
  white: "#FFFFFF",
  dark: "#0D2232",
  dark2: "#123B4E",
};

export const FONT = "PingFang SC";

export function line(color = C.line, width = 1) {
  return { style: "solid", fill: color, width };
}

export function bg(ctx, slide, opts = {}) {
  const fill = opts.dark ? C.dark : C.paper;
  ctx.addShape(slide, { x: 0, y: 0, w: ctx.W, h: ctx.H, fill, line: line(fill, 0) });
  if (!opts.dark) {
    ctx.addShape(slide, { x: 0, y: 0, w: ctx.W, h: 9, fill: C.tealDark, line: line(C.tealDark, 0) });
  }
}

export function text(ctx, slide, value, x, y, w, h, opts = {}) {
  const s = ctx.addText(slide, {
    text: value,
    x,
    y,
    w,
    h,
    fontSize: opts.size ?? 22,
    color: opts.color ?? C.ink,
    bold: opts.bold ?? false,
    typeface: opts.face ?? FONT,
    align: opts.align ?? "left",
    valign: opts.valign ?? "top",
    fill: opts.fill ?? "#00000000",
    line: opts.border ? line(opts.border, opts.borderWidth ?? 1) : line("#00000000", 0),
    insets: opts.insets ?? { left: 0, right: 0, top: 0, bottom: 0 },
    name: opts.name,
  });
  if (opts.leading) s.text.lineSpacing = opts.leading;
  if (opts.autoFit !== false) s.text.autoFit = "shrinkText";
  return s;
}

export function kicker(ctx, slide, label, x = 70, y = 46, color = C.cyan) {
  ctx.addShape(slide, { x, y: y + 5, w: 8, h: 8, fill: color, line: line(color, 0) });
  return text(ctx, slide, label, x + 18, y, 360, 22, {
    size: 13,
    color,
    bold: true,
  });
}

export function title(ctx, slide, value, x = 70, y = 76, w = 760, h = 92, opts = {}) {
  return text(ctx, slide, value, x, y, w, h, {
    size: opts.size ?? 42,
    color: opts.color ?? C.ink,
    bold: true,
    leading: opts.leading ?? 1.05,
  });
}

export function subcopy(ctx, slide, value, x, y, w, h, opts = {}) {
  return text(ctx, slide, value, x, y, w, h, {
    size: opts.size ?? 20,
    color: opts.color ?? C.muted,
    leading: opts.leading ?? 1.18,
  });
}

export function footer(ctx, slide, source, n) {
  text(ctx, slide, source, 70, 684, 860, 18, { size: 10, color: "#8A8378" });
  text(ctx, slide, String(n).padStart(2, "0"), 1184, 674, 34, 22, {
    size: 13,
    color: "#8A8378",
    align: "right",
  });
}

export function panel(ctx, slide, x, y, w, h, opts = {}) {
  return ctx.addShape(slide, {
    x,
    y,
    w,
    h,
    fill: opts.fill ?? C.white,
    line: line(opts.border ?? C.line, opts.borderWidth ?? 1),
  });
}

export async function iconLabel(ctx, slide, icon, label, x, y, opts = {}) {
  await ctx.addLucideIcon(slide, {
    icon,
    x,
    y,
    w: opts.iconSize ?? 24,
    h: opts.iconSize ?? 24,
    color: opts.color ?? C.cyan,
    strokeWidth: 2,
    alt: label,
  });
  text(ctx, slide, label, x + (opts.iconSize ?? 24) + 10, y - 2, opts.w ?? 260, 30, {
    size: opts.size ?? 18,
    color: opts.textColor ?? C.ink,
    bold: opts.bold ?? true,
  });
}

export async function screenshot(ctx, slide, path, x, y, w, h, opts = {}) {
  panel(ctx, slide, x, y, w, h, { fill: C.white, border: opts.border ?? "#C9D0D8" });
  await ctx.addImage(slide, {
    path,
    x: x + (opts.pad ?? 8),
    y: y + (opts.pad ?? 8),
    w: w - 2 * (opts.pad ?? 8),
    h: h - 2 * (opts.pad ?? 8),
    fit: opts.fit ?? "contain",
    alt: opts.alt ?? "系统界面截图",
  });
  if (opts.caption) {
    text(ctx, slide, opts.caption, x, y + h + 8, w, 20, {
      size: 12,
      color: C.muted,
      align: opts.captionAlign ?? "center",
    });
  }
}

export function chip(ctx, slide, label, x, y, w, opts = {}) {
  panel(ctx, slide, x, y, w, opts.h ?? 32, {
    fill: opts.fill ?? C.cyanSoft,
    border: opts.border ?? "#BCECF1",
  });
  text(ctx, slide, label, x + 12, y + 6, w - 24, 18, {
    size: opts.size ?? 13,
    color: opts.color ?? C.tealDark,
    bold: opts.bold ?? true,
    align: opts.align ?? "center",
  });
}

export function divider(ctx, slide, x, y, w, color = C.line) {
  ctx.addShape(slide, { x, y, w, h: 1.2, fill: color, line: line(color, 0) });
}

export async function numberedStep(ctx, slide, num, icon, heading, body, x, y, w, opts = {}) {
  const accent = opts.color ?? C.cyan;
  panel(ctx, slide, x, y, w, opts.h ?? 102, { fill: opts.fill ?? C.white, border: opts.border ?? C.line });
  ctx.addShape(slide, { x: x + 16, y: y + 18, w: 30, h: 30, geometry: "ellipse", fill: accent, line: line(accent, 0) });
  text(ctx, slide, String(num), x + 16, y + 23, 30, 18, { size: 13, color: C.white, bold: true, align: "center" });
  await ctx.addLucideIcon(slide, { icon, x: x + 56, y: y + 20, w: 22, h: 22, color: accent, alt: heading });
  text(ctx, slide, heading, x + 86, y + 18, w - 104, 26, { size: 18, bold: true, color: C.ink });
  subcopy(ctx, slide, body, x + 56, y + 50, w - 74, 42, { size: 14, color: C.muted, leading: 1.15 });
}

export function smallSource() {
  return "FNTL-MS100 贝通云网管系统 | 产品介绍";
}
