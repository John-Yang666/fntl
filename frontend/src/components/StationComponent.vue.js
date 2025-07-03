/// <reference types="../../node_modules/.vue-global-types/vue_3.5_false.d.ts" />
import { __assign } from "tslib";
export default (await import('vue')).defineComponent({
    props: ['station'],
});
; /* PartiallyEnd: #3632/script.vue */
function __VLS_template() {
    var __VLS_ctx = {};
    var __VLS_localComponents = __assign(__assign({}, {}), __VLS_ctx);
    var __VLS_components;
    var __VLS_localDirectives = __assign(__assign({}, {}), __VLS_ctx);
    var __VLS_directives;
    var __VLS_styleScopedClasses;
    var __VLS_resolvedLocalAndGlobalComponents;
    __VLS_elementAsFunction(__VLS_intrinsicElements.g, __VLS_intrinsicElements.g)({});
    __VLS_elementAsFunction(__VLS_intrinsicElements.rect)({ x: ((__VLS_ctx.station.x)), y: ((__VLS_ctx.station.y)), width: ("50"), height: ("50"), fill: ("lightgrey"), stroke: ("black"), "stroke-width": ("2"), });
    __VLS_elementAsFunction(__VLS_intrinsicElements.circle)({ cx: ((__VLS_ctx.station.x + 12.5)), cy: ((__VLS_ctx.station.y + 12.5)), r: ("5"), fill: ("red"), });
    __VLS_elementAsFunction(__VLS_intrinsicElements.circle)({ cx: ((__VLS_ctx.station.x + 37.5)), cy: ((__VLS_ctx.station.y + 12.5)), r: ("5"), fill: ("green"), });
    __VLS_elementAsFunction(__VLS_intrinsicElements.circle)({ cx: ((__VLS_ctx.station.x + 12.5)), cy: ((__VLS_ctx.station.y + 37.5)), r: ("5"), fill: ("blue"), });
    __VLS_elementAsFunction(__VLS_intrinsicElements.circle)({ cx: ((__VLS_ctx.station.x + 37.5)), cy: ((__VLS_ctx.station.y + 37.5)), r: ("5"), fill: ("yellow"), });
    __VLS_elementAsFunction(__VLS_intrinsicElements.text, __VLS_intrinsicElements.text)({ x: ((__VLS_ctx.station.x)), y: ((__VLS_ctx.station.y + 65)), fill: ("black"), });
    (__VLS_ctx.station.name);
    var __VLS_slots;
    var __VLS_inheritedAttrs;
    var __VLS_refs = {};
    var $refs;
    var $el;
    return {
        attrs: {},
        slots: __VLS_slots,
        refs: $refs,
        rootEl: $el,
    };
}
;
var __VLS_self;
