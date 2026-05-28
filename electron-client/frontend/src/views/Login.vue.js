/// <reference types="../../node_modules/.vue-global-types/vue_3.5_false.d.ts" />
import { __assign, __awaiter, __generator } from "tslib";
import { defineComponent, ref, onMounted } from 'vue';
import { useUserStore } from '@/stores/userStore';
import { useRouter, useRoute } from 'vue-router';
export default defineComponent({
    setup: function () {
        var _this = this;
        var userStore = useUserStore();
        var router = useRouter();
        var route = useRoute();
        var username = ref('');
        var password = ref('');
        var error = ref('');
        var handleLogin = function () { return __awaiter(_this, void 0, void 0, function () {
            var redirectPath, err_1;
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0:
                        _a.trys.push([0, 2, , 3]);
                        return [4 /*yield*/, userStore.login(username.value, password.value)];
                    case 1:
                        _a.sent();
                        redirectPath = route.query.redirect || '/';
                        router.push(redirectPath);
                        return [3 /*break*/, 3];
                    case 2:
                        err_1 = _a.sent();
                        error.value = 'Failed to login. Please check your credentials.';
                        return [3 /*break*/, 3];
                    case 3: return [2 /*return*/];
                }
            });
        }); };
        onMounted(function () { return __awaiter(_this, void 0, void 0, function () {
            var token, redirectPath, _a;
            return __generator(this, function (_b) {
                switch (_b.label) {
                    case 0:
                        token = JSON.parse(localStorage.getItem('token') || '{}');
                        if (!(token && token.access)) return [3 /*break*/, 4];
                        _b.label = 1;
                    case 1:
                        _b.trys.push([1, 3, , 4]);
                        return [4 /*yield*/, userStore.fetchUserDetails()];
                    case 2:
                        _b.sent();
                        redirectPath = route.query.redirect || '/';
                        router.push(redirectPath); // Redirect if user is already logged in
                        return [3 /*break*/, 4];
                    case 3:
                        _a = _b.sent();
                        userStore.logout();
                        return [3 /*break*/, 4];
                    case 4: return [2 /*return*/];
                }
            });
        }); });
        return {
            username: username,
            password: password,
            error: error,
            handleLogin: handleLogin
        };
    }
});
; /* PartiallyEnd: #3632/script.vue */
function __VLS_template() {
    var __VLS_ctx = {};
    var __VLS_localComponents = __assign(__assign({}, {}), __VLS_ctx);
    var __VLS_components;
    var __VLS_localDirectives = __assign(__assign({}, {}), __VLS_ctx);
    var __VLS_directives;
    var __VLS_styleScopedClasses;
    __VLS_styleScopedClasses['login-button'];
    // CSS variable injection 
    // CSS variable injection end 
    var __VLS_resolvedLocalAndGlobalComponents;
    __VLS_elementAsFunction(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: ("login-container") }));
    __VLS_elementAsFunction(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: ("login-header") }));
    __VLS_elementAsFunction(__VLS_intrinsicElements.h2, __VLS_intrinsicElements.h2)({});
    __VLS_elementAsFunction(__VLS_intrinsicElements.form, __VLS_intrinsicElements.form)(__assign({ onSubmit: (__VLS_ctx.handleLogin) }));
    __VLS_elementAsFunction(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: ("input-group") }));
    __VLS_elementAsFunction(__VLS_intrinsicElements.label, __VLS_intrinsicElements.label)({ for: ("username"), });
    __VLS_elementAsFunction(__VLS_intrinsicElements.input)({ value: ((__VLS_ctx.username)), id: ("username"), type: ("text"), required: (true), });
    __VLS_elementAsFunction(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: ("input-group") }));
    __VLS_elementAsFunction(__VLS_intrinsicElements.label, __VLS_intrinsicElements.label)({ for: ("password"), });
    __VLS_elementAsFunction(__VLS_intrinsicElements.input)({ id: ("password"), type: ("password"), required: (true), });
    (__VLS_ctx.password);
    __VLS_elementAsFunction(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign({ type: ("submit") }, { class: ("login-button") }));
    if (__VLS_ctx.error) {
        __VLS_elementAsFunction(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)(__assign({ class: ("error-message") }));
        (__VLS_ctx.error);
    }
    __VLS_styleScopedClasses['login-container'];
    __VLS_styleScopedClasses['login-header'];
    __VLS_styleScopedClasses['input-group'];
    __VLS_styleScopedClasses['input-group'];
    __VLS_styleScopedClasses['login-button'];
    __VLS_styleScopedClasses['error-message'];
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
