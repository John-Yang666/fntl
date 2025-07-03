/// <reference types="../../node_modules/.vue-global-types/vue_3.5_false.d.ts" />
import { __assign, __spreadArray } from "tslib";
import { ref } from 'vue';
import { useRoute } from 'vue-router';
import DetailedStatusComponent from '@/components/DetailedStatusComponent.vue';
import AsideComponent from '@/components/AsideComponent.vue';
import AnalogDataChart from '@/components/AnalogDataChart.vue';
import DeviceNameComponent from '@/components/DeviceNameComponent.vue';
import CommandReplyComponent from '@/components/CommandReplyComponent.vue';
var _a = await import('vue'), defineProps = _a.defineProps, defineSlots = _a.defineSlots, defineEmits = _a.defineEmits, defineExpose = _a.defineExpose, defineModel = _a.defineModel, defineOptions = _a.defineOptions, withDefaults = _a.withDefaults;
var route = useRoute();
var deviceName = ref(''); // 设备名称
var showAnalogDataChart = ref(false); // 控制 AnalogDataChart 显示
var updateDeviceName = function (name) {
    deviceName.value = name;
};
var loadAnalogDataChart = function () {
    showAnalogDataChart.value = true;
};
// 打开新窗口
var openInNewWindow = function () {
    var url = window.location.href;
    var width = window.screen.width;
    var height = window.screen.height / 2;
    window.open(url, '_blank', "width=".concat(width, ",height=").concat(height));
};
// 打开切换模式窗口
var openSwitchModeWindow = function () {
    var idStr = route.params.index;
    var url = "".concat(window.location.origin, "/switch-mode/").concat(idStr);
    window.open(url, '_blank', 'width=500,height=400');
};
//打开重启命令窗口
var openRestartCommandWindow = function () {
    var idStr = route.params.index;
    var url = "".concat(window.location.origin, "/restart-command/").concat(idStr);
    window.open(url, '_blank', 'width=500,height=400');
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
    var __VLS_0 = __VLS_resolvedLocalAndGlobalComponents.ElContainer;
    /** @type { [typeof __VLS_components.ElContainer, typeof __VLS_components.elContainer, typeof __VLS_components.ElContainer, typeof __VLS_components.elContainer, ] } */
    // @ts-ignore
    var __VLS_1 = __VLS_asFunctionalComponent(__VLS_0, new __VLS_0({}));
    var __VLS_2 = __VLS_1.apply(void 0, __spreadArray([{}], __VLS_functionalComponentArgsRest(__VLS_1), false));
    var __VLS_6 = {};
    var __VLS_7 = __VLS_resolvedLocalAndGlobalComponents.ElAside;
    /** @type { [typeof __VLS_components.ElAside, typeof __VLS_components.elAside, typeof __VLS_components.ElAside, typeof __VLS_components.elAside, ] } */
    // @ts-ignore
    var __VLS_8 = __VLS_asFunctionalComponent(__VLS_7, new __VLS_7({}));
    var __VLS_9 = __VLS_8.apply(void 0, __spreadArray([{}], __VLS_functionalComponentArgsRest(__VLS_8), false));
    // @ts-ignore
    [AsideComponent, AsideComponent,];
    // @ts-ignore
    var __VLS_13 = __VLS_asFunctionalComponent(AsideComponent, new AsideComponent(__assign({ 'onDeviceSelected': {} })));
    var __VLS_14 = __VLS_13.apply(void 0, __spreadArray([__assign({ 'onDeviceSelected': {} })], __VLS_functionalComponentArgsRest(__VLS_13), false));
    var __VLS_18;
    var __VLS_19 = {
        onDeviceSelected: (__VLS_ctx.updateDeviceName)
    };
    var __VLS_15;
    var __VLS_16;
    var __VLS_17;
    __VLS_nonNullable(__VLS_12.slots).default;
    var __VLS_12;
    var __VLS_20 = __VLS_resolvedLocalAndGlobalComponents.ElMain;
    /** @type { [typeof __VLS_components.ElMain, typeof __VLS_components.elMain, typeof __VLS_components.ElMain, typeof __VLS_components.elMain, ] } */
    // @ts-ignore
    var __VLS_21 = __VLS_asFunctionalComponent(__VLS_20, new __VLS_20({}));
    var __VLS_22 = __VLS_21.apply(void 0, __spreadArray([{}], __VLS_functionalComponentArgsRest(__VLS_21), false));
    __VLS_elementAsFunction(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({});
    // @ts-ignore
    [DeviceNameComponent, DeviceNameComponent,];
    // @ts-ignore
    var __VLS_26 = __VLS_asFunctionalComponent(DeviceNameComponent, new DeviceNameComponent({}));
    var __VLS_27 = __VLS_26.apply(void 0, __spreadArray([{}], __VLS_functionalComponentArgsRest(__VLS_26), false));
    var __VLS_31 = __VLS_resolvedLocalAndGlobalComponents.ElButton;
    /** @type { [typeof __VLS_components.ElButton, typeof __VLS_components.elButton, typeof __VLS_components.ElButton, typeof __VLS_components.elButton, ] } */
    // @ts-ignore
    var __VLS_32 = __VLS_asFunctionalComponent(__VLS_31, new __VLS_31(__assign({ 'onClick': {} })));
    var __VLS_33 = __VLS_32.apply(void 0, __spreadArray([__assign({ 'onClick': {} })], __VLS_functionalComponentArgsRest(__VLS_32), false));
    var __VLS_37;
    var __VLS_38 = {
        onClick: (__VLS_ctx.loadAnalogDataChart)
    };
    var __VLS_34;
    var __VLS_35;
    __VLS_nonNullable(__VLS_36.slots).default;
    var __VLS_36;
    var __VLS_39 = __VLS_resolvedLocalAndGlobalComponents.ElButton;
    /** @type { [typeof __VLS_components.ElButton, typeof __VLS_components.elButton, typeof __VLS_components.ElButton, typeof __VLS_components.elButton, ] } */
    // @ts-ignore
    var __VLS_40 = __VLS_asFunctionalComponent(__VLS_39, new __VLS_39(__assign({ 'onClick': {} })));
    var __VLS_41 = __VLS_40.apply(void 0, __spreadArray([__assign({ 'onClick': {} })], __VLS_functionalComponentArgsRest(__VLS_40), false));
    var __VLS_45;
    var __VLS_46 = {
        onClick: (__VLS_ctx.openRestartCommandWindow)
    };
    var __VLS_42;
    var __VLS_43;
    __VLS_nonNullable(__VLS_44.slots).default;
    var __VLS_44;
    var __VLS_47 = __VLS_resolvedLocalAndGlobalComponents.ElButton;
    /** @type { [typeof __VLS_components.ElButton, typeof __VLS_components.elButton, typeof __VLS_components.ElButton, typeof __VLS_components.elButton, ] } */
    // @ts-ignore
    var __VLS_48 = __VLS_asFunctionalComponent(__VLS_47, new __VLS_47(__assign({ 'onClick': {} }, { class: ("right-button2") })));
    var __VLS_49 = __VLS_48.apply(void 0, __spreadArray([__assign({ 'onClick': {} }, { class: ("right-button2") })], __VLS_functionalComponentArgsRest(__VLS_48), false));
    var __VLS_53;
    var __VLS_54 = {
        onClick: (__VLS_ctx.openSwitchModeWindow)
    };
    var __VLS_50;
    var __VLS_51;
    __VLS_nonNullable(__VLS_52.slots).default;
    var __VLS_52;
    var __VLS_55 = __VLS_resolvedLocalAndGlobalComponents.ElButton;
    /** @type { [typeof __VLS_components.ElButton, typeof __VLS_components.elButton, typeof __VLS_components.ElButton, typeof __VLS_components.elButton, ] } */
    // @ts-ignore
    var __VLS_56 = __VLS_asFunctionalComponent(__VLS_55, new __VLS_55(__assign({ 'onClick': {} }, { class: ("right-button") })));
    var __VLS_57 = __VLS_56.apply(void 0, __spreadArray([__assign({ 'onClick': {} }, { class: ("right-button") })], __VLS_functionalComponentArgsRest(__VLS_56), false));
    var __VLS_61;
    var __VLS_62 = {
        onClick: (__VLS_ctx.openInNewWindow)
    };
    var __VLS_58;
    var __VLS_59;
    __VLS_nonNullable(__VLS_60.slots).default;
    var __VLS_60;
    // @ts-ignore
    [CommandReplyComponent, CommandReplyComponent,];
    // @ts-ignore
    var __VLS_63 = __VLS_asFunctionalComponent(CommandReplyComponent, new CommandReplyComponent({}));
    var __VLS_64 = __VLS_63.apply(void 0, __spreadArray([{}], __VLS_functionalComponentArgsRest(__VLS_63), false));
    if (__VLS_ctx.showAnalogDataChart) {
        __VLS_elementAsFunction(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({});
        // @ts-ignore
        [AnalogDataChart, AnalogDataChart,];
        // @ts-ignore
        var __VLS_68 = __VLS_asFunctionalComponent(AnalogDataChart, new AnalogDataChart({}));
        var __VLS_69 = __VLS_68.apply(void 0, __spreadArray([{}], __VLS_functionalComponentArgsRest(__VLS_68), false));
    }
    // @ts-ignore
    [DetailedStatusComponent, DetailedStatusComponent,];
    // @ts-ignore
    var __VLS_73 = __VLS_asFunctionalComponent(DetailedStatusComponent, new DetailedStatusComponent({}));
    var __VLS_74 = __VLS_73.apply(void 0, __spreadArray([{}], __VLS_functionalComponentArgsRest(__VLS_73), false));
    __VLS_nonNullable(__VLS_25.slots).default;
    var __VLS_25;
    __VLS_nonNullable(__VLS_5.slots).default;
    var __VLS_5;
    __VLS_styleScopedClasses['right-button2'];
    __VLS_styleScopedClasses['right-button'];
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
            DetailedStatusComponent: DetailedStatusComponent,
            AsideComponent: AsideComponent,
            AnalogDataChart: AnalogDataChart,
            DeviceNameComponent: DeviceNameComponent,
            CommandReplyComponent: CommandReplyComponent,
            showAnalogDataChart: showAnalogDataChart,
            updateDeviceName: updateDeviceName,
            loadAnalogDataChart: loadAnalogDataChart,
            openInNewWindow: openInNewWindow,
            openSwitchModeWindow: openSwitchModeWindow,
            openRestartCommandWindow: openRestartCommandWindow,
        };
    },
});
export default (await import('vue')).defineComponent({
    setup: function () {
        return {};
    },
    __typeEl: {},
});
; /* PartiallyEnd: #4569/main.vue */
