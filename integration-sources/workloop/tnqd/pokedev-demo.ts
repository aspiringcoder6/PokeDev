/** Isolated preview profile: real TNQD component, explicit synthetic data and read-only demo permissions. */
import { Component, inject, importProvidersFrom, signal } from '@angular/core';
import { bootstrapApplication } from '@angular/platform-browser';
import { provideAnimations } from '@angular/platform-browser/animations';
import { provideRouter } from '@angular/router';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { registerLocaleData } from '@angular/common';
import vi from '@angular/common/locales/vi';
import { provideTransloco, TranslocoService } from '@jsverse/transloco';
import { VTS_I18N, VTS_DATE_LOCALE, vi_VN } from '@new-vts-kit/ng-vts/i18n';
import { VtsMessageService } from '@new-vts-kit/ng-vts/message';
import { VtsModalModule } from '@new-vts-kit/ng-vts/modal';
import { VtsToastModule, VtsToastService } from '@new-vts-kit/ng-vts/toast';
import { VtsThemeModule } from '@new-vts-kit/theme/services';
import { of } from 'rxjs';
import { AuthzService } from '@/core/authz';
import { AuthService } from '@/core/auth';
import { iconLoaderProviders } from '@/shared/providers/icon-loader.config';
import { GLOBAL_DATE_LOCALE } from '@/shared/providers/global-date-locale';
import { MembershipListComponent } from '@/modules/military-youth/membership-roster/components/membership-list/membership-list.component';
import tnqdVi from '@/modules/military-youth/i18n/vi.json';
import baseVi from './assets/i18n/vi.json';

registerLocaleData(vi);
class DemoTranslations { getTranslation() { return of({ ...baseVi, tnqd: tnqdVi }); } }
const readOnly = {
  can: (action: string) => ['xem', 'view', 'read', 'xem_ds'].includes(action),
  loadObjectPermissions: async () => { await new Promise(resolve => setTimeout(resolve, 80)); },
  loadModuleRbac: async () => {}, isInitialized: () => true,
};
@Component({
  selector: 'app-root', standalone: true, imports: [MembershipListComponent],
  template: `
    <header class="pd-demo-top"><div><span class="pd-demo-mark">Đ</span><b>THANH NIÊN QUÂN ĐỘI</b></div><span class="pd-demo-pill">Môi trường demo · 45 hồ sơ mẫu</span></header>
    @if (!loggedIn()) {
      <main class="pd-demo-welcome"><span class="pd-demo-eyebrow">POKEDEV × MILITARY YOUTH</span><h1>Tra cứu rõ ràng.<br>Kết quả đáng tin cậy.</h1><p>Trình diễn cải tiến tìm kiếm trên component Angular thật của TNQD, với dữ liệu giả lập và quyền chỉ đọc.</p><button (click)="login()">Đăng nhập nhanh Dev <span>→</span></button><small>Không sử dụng hồ sơ thật. Đây là profile kiểm thử riêng.</small></main>
    } @else {
      <div class="pd-demo-body"><aside><span>XÂY DỰNG ĐOÀN</span><a class="pd-demo-active">Thông tin cán bộ, đoàn viên, thanh niên</a><p>Dữ liệu mẫu riêng cho demo</p><div class="pd-demo-note">Frontend được build từ source TNQD.<br>API danh sách dùng fixture cố định.</div></aside><main class="pd-demo-main"><div class="pd-demo-breadcrumb">Xây dựng Đoàn <span>/</span> Danh sách nhân sự</div><app-membership-list /></main></div>
    }
  `,
  styles: [`
    :host{display:block;min-height:100vh;color:#273142;background:#f3f5f8;font-family:Inter,Arial,sans-serif}.pd-demo-top{height:74px;display:flex;align-items:center;justify-content:space-between;padding:0 32px;background:white;border-bottom:1px solid #e6e9ef}.pd-demo-top>div{display:flex;align-items:center;gap:14px;font-size:17px;letter-spacing:.5px}.pd-demo-mark{display:grid;place-items:center;width:38px;height:42px;color:white;background:#8b1731;border-radius:8px;font-weight:800;font-size:24px}.pd-demo-pill{padding:7px 12px;border:1px solid #d5e6de;background:#f0f8f3;border-radius:20px;color:#28724e;font-size:12px}.pd-demo-body{display:flex;min-height:calc(100vh - 74px)}aside{width:230px;padding:28px 16px;background:white;border-right:1px solid #e6e9ef;flex-shrink:0}aside>span{font-size:11px;color:#8b93a2;letter-spacing:1px;padding:0 12px}.pd-demo-active{display:block;margin-top:18px;padding:14px;border-radius:8px;background:#f8ecef;border:1px solid #efd7dd;color:#8b1731;font-weight:600;line-height:1.6;font-size:13px}aside p,.pd-demo-note{padding:16px 12px;font-size:12px;line-height:1.7;color:#8992a2}.pd-demo-note{margin-top:70px;border-top:1px solid #e8ebf0}.pd-demo-main{flex:1;padding:20px;min-width:0}.pd-demo-breadcrumb{display:flex;gap:12px;font-size:12px;color:#7d8796;margin:0 0 18px}.pd-demo-breadcrumb span{color:#b6bfcb}.pd-demo-main app-membership-list{display:block;height:calc(100vh - 150px);min-height:500px}.pd-demo-welcome{max-width:760px;margin:90px auto;padding:20px 40px}.pd-demo-eyebrow{font-size:11px;letter-spacing:3px;color:#9a3450;font-weight:bold}.pd-demo-welcome h1{font-size:48px;line-height:1.15;margin:24px 0;color:#283244;letter-spacing:-1.5px}.pd-demo-welcome p{font-size:16px;color:#738092;line-height:1.9;max-width:580px}.pd-demo-welcome button{background:#8b1731;color:white;border:0;border-radius:9px;padding:15px 24px;font-weight:bold;display:flex;gap:40px;margin:28px 0 16px;cursor:pointer}.pd-demo-welcome small{color:#99a2af;font-size:12px}@media(max-width:700px){aside{display:none}.pd-demo-top{padding:0 16px}.pd-demo-top b{font-size:12px}.pd-demo-pill{font-size:9px;padding:6px}.pd-demo-main{padding:12px}.pd-demo-welcome{margin:55px auto;padding:20px}.pd-demo-welcome h1{font-size:36px}}`],
})
class DemoRoot {
  loggedIn = signal(false);
  constructor() {
    const transloco = inject(TranslocoService);
    transloco.setTranslation({ ...baseVi, tnqd: tnqdVi }, 'vi');
    transloco.setActiveLang('vi');
  }
  login() {
    window.history.replaceState({}, '', '/tnqd/youth-union-building/member-ship/list');
    this.loggedIn.set(true);
  }
}
bootstrapApplication(DemoRoot, { providers: [
  provideAnimations(), provideRouter([]), provideHttpClient(withInterceptors([
    (request, next) => next(request.url.startsWith('/military-youth/') ? request.clone({ url: '/api' + request.url }) : request),
  ])),
  provideTransloco({ config: { availableLangs: ['vi'], defaultLang: 'vi', fallbackLang: 'vi', reRenderOnLangChange: true, prodMode: true }, loader: DemoTranslations }),
  { provide: AuthzService, useValue: readOnly },
  { provide: AuthService, useValue: { isAuthenticated: () => true, getToken: () => '', getAccessToken: () => '', user: signal({ name: 'Demo chỉ đọc' }), user$: of({ name: 'Demo chỉ đọc', roles: [] }), hasPermission: () => false, getCurrentUser: () => of({ roles: [] }) } },
  { provide: VTS_I18N, useValue: vi_VN }, { provide: VTS_DATE_LOCALE, useValue: GLOBAL_DATE_LOCALE },
  VtsToastService, VtsMessageService, importProvidersFrom(VtsToastModule), importProvidersFrom(VtsModalModule),
  importProvidersFrom(VtsThemeModule.forRoot({ themes: [{ theme: 'default', url: '/assets/style-theme/theme-default.css' }], defaultTheme: 'default' })),
  iconLoaderProviders,
] }).catch(error => console.error('TNQD_DEMO_BOOTSTRAP', error));
