/// <reference types="../../node_modules/.vue-global-types/vue_3.5_false.d.ts" />
import { __assign, __spreadArray } from "tslib";
var _a = await import('vue'), defineProps = _a.defineProps, defineSlots = _a.defineSlots, defineEmits = _a.defineEmits, defineExpose = _a.defineExpose, defineModel = _a.defineModel, defineOptions = _a.defineOptions, withDefaults = _a.withDefaults;
var props = defineProps();
var getStatusClass = function (status) {
    return {
        'fault-status': status === '故障' || status === '无效',
        'normal-status': status === '正常'
    };
};
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
    var __VLS_0 = __VLS_resolvedLocalAndGlobalComponents.ElTableColumn;
    /** @type { [typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, typeof __VLS_components.ElTableColumn, typeof __VLS_components.elTableColumn, ] } */
    // @ts-ignore
    var __VLS_1 = __VLS_asFunctionalComponent(__VLS_0, new __VLS_0({ prop: ((__VLS_ctx.prop)), label: ((__VLS_ctx.label)), }));
    var __VLS_2 = __VLS_1.apply(void 0, __spreadArray([{ prop: ((__VLS_ctx.prop)), label: ((__VLS_ctx.label)), }], __VLS_functionalComponentArgsRest(__VLS_1), false));
    var __VLS_6 = {};
    __VLS_elementAsFunction(__VLS_intrinsicElements.template, __VLS_intrinsicElements.template)({});
    {
        var __VLS_thisSlot = __VLS_nonNullable(__VLS_5.slots).default;
        var scope = __VLS_getSlotParams(__VLS_thisSlot)[0];
        __VLS_elementAsFunction(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ class: ((__VLS_ctx.getStatusClass(scope.row[__VLS_ctx.prop]))) }));
        (scope.row[__VLS_ctx.prop]);
    }
    var __VLS_5;
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
        return {
            getStatusClass: getStatusClass,
        };
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
