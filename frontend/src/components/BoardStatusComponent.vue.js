/// <reference types="../../node_modules/.vue-global-types/vue_3.5_false.d.ts" />
import { __assign, __spreadArray } from "tslib";
// 定义一个接口用于描述单个板卡的属性
var _a = await import('vue'), defineProps = _a.defineProps, defineSlots = _a.defineSlots, defineEmits = _a.defineEmits, defineExpose = _a.defineExpose, defineModel = _a.defineModel, defineOptions = _a.defineOptions, withDefaults = _a.withDefaults;
var props = defineProps();
; /* PartiallyEnd: #3632/scriptSetup.vue */
var __VLS_fnComponent = (await import('vue')).defineComponent({});
;
var __VLS_functionalComponentProps;
function __VLS_template() {
    var __VLS_ctx = {};
    var __VLS_localComponents = __assign(__assign(__assign({}, {}), {}), __VLS_ctx);
    var __VLS_components;
    var __VLS_localDirectives = __assign(__assign({}, {}), __VLS_ctx);
    var __VLS_directives;
    var __VLS_styleScopedClasses;
    // CSS variable injection 
    // CSS variable injection end 
    var __VLS_resolvedLocalAndGlobalComponents;
    var __VLS_0 = __VLS_resolvedLocalAndGlobalComponents.ElRow;
    /** @type { [typeof __VLS_components.ElRow, typeof __VLS_components.elRow, typeof __VLS_components.ElRow, typeof __VLS_components.elRow, ] } */
    // @ts-ignore
    var __VLS_1 = __VLS_asFunctionalComponent(__VLS_0, new __VLS_0(__assign({ class: ("board-status") })));
    var __VLS_2 = __VLS_1.apply(void 0, __spreadArray([__assign({ class: ("board-status") })], __VLS_functionalComponentArgsRest(__VLS_1), false));
    var __VLS_6 = {};
    for (var _i = 0, _a = __VLS_getVForSourceType((__VLS_ctx.boards)); _i < _a.length; _i++) {
        var board = _a[_i][0];
        var __VLS_7 = __VLS_resolvedLocalAndGlobalComponents.ElCol;
        /** @type { [typeof __VLS_components.ElCol, typeof __VLS_components.elCol, typeof __VLS_components.ElCol, typeof __VLS_components.elCol, ] } */
        // @ts-ignore
        var __VLS_8 = __VLS_asFunctionalComponent(__VLS_7, new __VLS_7({ span: ((4)), key: ((board.name)), }));
        var __VLS_9 = __VLS_8.apply(void 0, __spreadArray([{ span: ((4)), key: ((board.name)), }], __VLS_functionalComponentArgsRest(__VLS_8), false));
        var __VLS_13 = __VLS_resolvedLocalAndGlobalComponents.ElCard;
        /** @type { [typeof __VLS_components.ElCard, typeof __VLS_components.elCard, typeof __VLS_components.ElCard, typeof __VLS_components.elCard, ] } */
        // @ts-ignore
        var __VLS_14 = __VLS_asFunctionalComponent(__VLS_13, new __VLS_13({ bodyStyle: (({ padding: '20px' })), }));
        var __VLS_15 = __VLS_14.apply(void 0, __spreadArray([{ bodyStyle: (({ padding: '20px' })), }], __VLS_functionalComponentArgsRest(__VLS_14), false));
        __VLS_elementAsFunction(__VLS_intrinsicElements.h5, __VLS_intrinsicElements.h5)({});
        (board.name);
        __VLS_elementAsFunction(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: (({ 'status-indicator': true, 'is-good': board.status === '正常' || '主用' || '备用', 'is-bad': board.status === '故障', 'is-null': board.status === 'null' })) }));
        (board.status);
        __VLS_nonNullable(__VLS_18.slots).default;
        var __VLS_18;
        __VLS_nonNullable(__VLS_12.slots).default;
        var __VLS_12;
    }
    __VLS_nonNullable(__VLS_5.slots).default;
    var __VLS_5;
    __VLS_styleScopedClasses['board-status'];
    __VLS_styleScopedClasses['status-indicator'];
    __VLS_styleScopedClasses['is-good'];
    __VLS_styleScopedClasses['is-bad'];
    __VLS_styleScopedClasses['is-null'];
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
var __VLS_self = (await import('vue')).defineComponent({
    setup: function () {
        return {};
    },
    __typeProps: {},
});
export default (await import('vue')).defineComponent({
    setup: function () {
        return {};
    },
    __typeProps: {},
    __typeEl: {},
});
; /* PartiallyEnd: #4569/main.vue */
