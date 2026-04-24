import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  Cpu,
  Database,
  Globe,
  Loader2,
  MessageSquare,
  Power,
  RefreshCw,
  Send,
  Settings,
  Zap,
} from 'lucide-react';
import { cn } from '../lib/utils';
import {
  monitorApi,
  systemApi,
  type DataflowProvidersPayload,
  type ThsBridgeStatePayload,
} from '../services/api';

interface ConfigSectionProps {
  title: string;
  icon: React.ElementType;
  children: React.ReactNode;
}

interface LlmConfigState {
  base_url: string;
  model: string;
  temperature: number | null;
  api_key: string;
}

const toOptionalNumber = (value: unknown): number | null => {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === 'string' && value.trim() === '') {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const ConfigSection: React.FC<ConfigSectionProps> = ({ title, icon: Icon, children }) => (
  <div className="bg-bg-card/30 border border-border rounded-lg overflow-hidden transition-all hover:bg-bg-card/50">
    <div className="bg-bg-card/50 border-b border-border p-4 flex items-center gap-3">
      <Icon className="h-4 w-4 text-neon-cyan" />
      <h3 className="text-[10px] font-orbitron text-white tracking-[0.2em] uppercase">{title}</h3>
    </div>
    <div className="p-5 space-y-4">{children}</div>
  </div>
);

export const SystemConfig: React.FC = () => {
  const [tushareStatus, setTushareStatus] = useState<'NONE' | 'TESTING' | 'OK' | 'ERROR'>('NONE');
  const [isSaving, setIsSaving] = useState(false);
  const [isTestingNotification, setIsTestingNotification] = useState(false);
  const [isRefreshingProviders, setIsRefreshingProviders] = useState(false);
  const [isRefreshingBridge, setIsRefreshingBridge] = useState(false);
  const [bridgeAction, setBridgeAction] = useState<'starting' | 'stopping' | ''>('');
  const [switchingProvider, setSwitchingProvider] = useState('');
  const [showSuccess, setShowSuccess] = useState(false);
  const [showError, setShowError] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [bridgeNotice, setBridgeNotice] = useState('');
  const [bridgeError, setBridgeError] = useState('');

  const [tushareToken, setTushareToken] = useState('••••••••••••••••••••••••••••••••');
  const [llmConfig, setLlmConfig] = useState<LlmConfigState>({
    base_url: 'https://api.openai.com/v1',
    model: 'gpt-4o-2024-05-13',
    temperature: null,
    api_key: '••••••••••••••••••••••••••••••••',
  });
  const [webhookUrl, setWebhookUrl] = useState('');
  const [dingtalkSecret, setDingtalkSecret] = useState('••••••••••••••••••••••••••••••••');
  const [dataflowCatalog, setDataflowCatalog] = useState<DataflowProvidersPayload>({
    current_provider: '',
    current_provider_display_name: '',
    providers: [],
  });
  const [bridgeState, setBridgeState] = useState<Record<string, unknown>>({});

  const applyProviderCatalog = (payload: DataflowProvidersPayload) => {
    setDataflowCatalog({
      current_provider: String(payload.current_provider ?? ''),
      current_provider_display_name: String(payload.current_provider_display_name ?? ''),
      providers: Array.isArray(payload.providers) ? payload.providers : [],
      summary: payload.summary ?? {},
      quality: payload.quality ?? {},
      tuning: payload.tuning ?? {},
      runtime_config: payload.runtime_config ?? {},
    });
  };

  const extractBridgeState = (payload: unknown): Record<string, unknown> => {
    if (!payload || typeof payload !== 'object') {
      return {};
    }
    const source = payload as Record<string, unknown>;
    if (source.ths_bridge && typeof source.ths_bridge === 'object') {
      return source.ths_bridge as Record<string, unknown>;
    }
    return {};
  };

  const applyBridgeState = (payload: unknown) => {
    setBridgeState(extractBridgeState(payload));
  };

  const refreshDataflowProviders = async () => {
    setIsRefreshingProviders(true);
    try {
      const payload = await systemApi.getDataflowProviders<DataflowProvidersPayload>();
      applyProviderCatalog(payload);
    } catch {
      // 忽略刷新失败，保留当前状态
    } finally {
      setIsRefreshingProviders(false);
    }
  };

  const refreshBridgeState = async () => {
    setIsRefreshingBridge(true);
    setBridgeError('');
    try {
      const payload = await systemApi.getThsBridgeState<ThsBridgeStatePayload>();
      applyBridgeState(payload);
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : 'Bridge 状态刷新失败。';
      setBridgeError(errMsg);
    } finally {
      setIsRefreshingBridge(false);
    }
  };

  useEffect(() => {
    const fetchConfigs = async () => {
      try {
        const [sysData, llmData, providerData, bridgeData] = await Promise.all([
          systemApi.getConfig(),
          systemApi.getLlmConfig(),
          systemApi.getDataflowProviders<DataflowProvidersPayload>(),
          systemApi.getThsBridgeState<ThsBridgeStatePayload>(),
        ]);
        if (sysData) {
          setTushareToken(String(sysData.tushare_token ?? '••••••••••••••••••••••••••••••••'));
          setWebhookUrl(String(sysData.wechat_webhook ?? ''));
          setDingtalkSecret(String(sysData.dingtalk_secret ?? '••••••••••••••••••••••••••••••••'));
        }

        const config = llmData.config ?? llmData;
        setLlmConfig({
          base_url: String(config.base_url ?? 'https://api.openai.com/v1'),
          model: String(config.model ?? 'gpt-4o-2024-05-13'),
          temperature: toOptionalNumber(config.temperature),
          api_key: String(config.api_key ?? '••••••••••••••••••••••••••••••••'),
        });

        applyProviderCatalog(providerData);
        applyBridgeState(bridgeData);
      } catch {
        // 使用默认值
      }
    };
    void fetchConfigs();
  }, []);

  const switchDataflowProvider = async (provider: string) => {
    setSwitchingProvider(provider);
    setShowError(false);
    try {
      const payload = await systemApi.switchDataflowProvider<DataflowProvidersPayload>({
        provider,
        persist: true,
      });
      applyProviderCatalog(payload);
      setShowSuccess(true);
      setTimeout(() => setShowSuccess(false), 3000);
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : '切换数据源失败。';
      setErrorMessage(errMsg);
      setShowError(true);
      setTimeout(() => setShowError(false), 5000);
    } finally {
      setSwitchingProvider('');
    }
  };

  const testTushare = async (e: React.MouseEvent) => {
    e.preventDefault();
    setTushareStatus('TESTING');
    setShowError(false);

    try {
      const tokenMasked = tushareToken.includes('*') || tushareToken.includes('•');
      if (!tokenMasked) {
        await systemApi.updateConfig({ tushare_token: tushareToken });
      }

      const payload = await monitorApi.getDataHealth<{ status?: string; message?: string }>();
      const status = String(payload.status || '').toLowerCase();

      if (!['provider_not_found', 'unknown'].includes(status)) {
        setTushareStatus('OK');
      } else {
        setTushareStatus('ERROR');
        setErrorMessage(String(payload.message ?? '数据源连通性测试失败。'));
        setShowError(true);
        setTimeout(() => setShowError(false), 5000);
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : '数据源连接失败。';
      setTushareStatus('ERROR');
      setErrorMessage(errMsg);
      setShowError(true);
      setTimeout(() => setShowError(false), 5000);
    }
  };

  const testNotification = async (e: React.MouseEvent) => {
    e.preventDefault();
    setIsTestingNotification(true);
    setShowError(false);
    setShowSuccess(false);

    try {
      await systemApi.testWechatNotification({ webhook_url: webhookUrl, channel: 'wechat' });
      setShowSuccess(true);
      setTimeout(() => setShowSuccess(false), 3000);
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : '通知测试失败';
      setErrorMessage(errMsg);
      setShowError(true);
      setTimeout(() => setShowError(false), 5000);
    } finally {
      setIsTestingNotification(false);
    }
  };

  const handleSave = async (e: React.MouseEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setShowSuccess(false);
    setShowError(false);

    try {
      const llmPayload = {
        ...llmConfig,
        temperature: llmConfig.temperature === null ? undefined : llmConfig.temperature,
        api_key: llmConfig.api_key.includes('*') || llmConfig.api_key.includes('•') ? '' : llmConfig.api_key,
        retain_api_key: llmConfig.api_key.includes('*') || llmConfig.api_key.includes('•'),
      };

      await Promise.all([
        systemApi.updateConfig({
          tushare_token: tushareToken.includes('*') || tushareToken.includes('•') ? undefined : tushareToken,
          wechat_webhook: webhookUrl,
          dingtalk_secret: dingtalkSecret.includes('*') || dingtalkSecret.includes('•') ? undefined : dingtalkSecret,
        }),
        systemApi.updateLlmConfig(llmPayload),
      ]);

      setShowSuccess(true);
      setTimeout(() => setShowSuccess(false), 3000);
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : '保存配置失败。';
      setErrorMessage(errMsg);
      setShowError(true);
      setTimeout(() => setShowError(false), 5000);
    } finally {
      setIsSaving(false);
    }
  };

  const startBridge = async (e: React.MouseEvent) => {
    e.preventDefault();
    setBridgeAction('starting');
    setBridgeError('');
    setBridgeNotice('');
    try {
      const payload = await systemApi.startThsBridge({
        channel: 'ths_ipc',
        restart: false,
        allow_disabled: true,
      });
      applyBridgeState(payload);
      setBridgeNotice('Bridge 启动请求已提交。');
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : 'Bridge 启动失败。';
      setBridgeError(errMsg);
    } finally {
      setBridgeAction('');
    }
  };

  const stopBridge = async (e: React.MouseEvent) => {
    e.preventDefault();
    setBridgeAction('stopping');
    setBridgeError('');
    setBridgeNotice('');
    try {
      const payload = await systemApi.stopThsBridge({
        force: true,
        reason: 'system_config_manual_stop',
      });
      applyBridgeState(payload);
      setBridgeNotice('Bridge 停止请求已提交。');
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : 'Bridge 停止失败。';
      setBridgeError(errMsg);
    } finally {
      setBridgeAction('');
    }
  };

  const bridgeStatus =
    bridgeAction === 'starting'
      ? 'STARTING'
      : bridgeAction === 'stopping'
        ? 'STOPPING'
        : Boolean(bridgeState.ready)
          ? 'READY'
          : Boolean(bridgeState.started || bridgeState.existing)
            ? 'STARTED'
            : 'IDLE';

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-8">
      <header className="mb-6">
        <h1 className="text-3xl font-orbitron font-extrabold text-white tracking-widest flex items-center gap-4">
          <Settings className="text-neon-cyan h-8 w-8" /> 系统配置
        </h1>
        <p className="text-info-gray/60 text-xs mt-2 uppercase tracking-[0.2em]">全局架构、数据源与通知配置</p>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <ConfigSection title="数据源配置" icon={Database}>
          <div className="p-3 bg-bg-primary/50 border border-border rounded flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Globe className="h-4 w-4 text-up-green" />
              <span className="text-xs font-mono text-white">
                当前主源: {dataflowCatalog.current_provider_display_name || '--'}
              </span>
            </div>
            <button
              type="button"
              onClick={() => void refreshDataflowProviders()}
              disabled={isRefreshingProviders}
              className="text-[9px] text-neon-cyan/90 font-mono uppercase bg-neon-cyan/10 px-1.5 py-0.5 rounded border border-neon-cyan/30 disabled:opacity-60"
            >
              {isRefreshingProviders ? '刷新中...' : '刷新状态'}
            </button>
          </div>

          <div className="space-y-2">
            <label className="text-[9px] text-info-gray/50 uppercase font-bold tracking-wider">Tushare Pro 令牌</label>
            <div className="flex gap-2">
              <input
                type="password"
                className="flex-1 bg-bg-primary border border-border rounded px-3 py-2 text-xs text-white outline-none focus:border-neon-cyan transition-colors"
                value={tushareToken}
                onChange={(e) => setTushareToken(e.target.value)}
              />
              <button
                type="button"
                onClick={testTushare}
                className={cn(
                  'px-4 py-2 rounded text-[10px] font-mono border transition-all uppercase flex items-center gap-2',
                  tushareStatus === 'OK'
                    ? 'bg-up-green/10 border-up-green text-up-green'
                    : tushareStatus === 'ERROR'
                      ? 'bg-down-red/10 border-down-red text-down-red'
                      : 'bg-neon-cyan/10 border-neon-cyan text-neon-cyan hover:bg-neon-cyan hover:text-black',
                )}
              >
                {tushareStatus === 'TESTING' ? <Loader2 className="h-3 w-3 animate-spin" /> : <Zap className="h-3 w-3" />}
                {tushareStatus === 'TESTING' ? '测试中...' : tushareStatus === 'OK' ? '已连接' : tushareStatus === 'ERROR' ? '测试失败' : '测试'}
              </button>
            </div>
          </div>

          <div className="space-y-2">
            {(dataflowCatalog.providers ?? []).map((provider) => {
              const name = String(provider.name ?? '').toLowerCase();
              const display = String(provider.display_name ?? (name || '--'));
              const enabled = Boolean(provider.enabled ?? false);
              const current = Boolean(provider.current ?? false);
              const switching = switchingProvider === name;
              const priority = toOptionalNumber(provider.priority);

              return (
                <div key={name} className="p-3 bg-bg-primary/50 border border-border rounded flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <Globe className={cn('h-4 w-4', current ? 'text-up-green' : 'text-info-gray/40')} />
                    <div className="flex flex-col">
                      <span className={cn('text-xs font-mono', current ? 'text-white' : 'text-info-gray/60')}>{display}</span>
                      <span className="text-[9px] font-mono text-info-gray/50 uppercase">
                        {enabled ? 'enabled' : 'disabled'} / priority {priority === null ? '--' : priority}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {current && (
                      <span className="text-[9px] text-up-green/80 font-mono uppercase bg-up-green/5 px-1.5 py-0.5 rounded border border-up-green/20">
                        当前
                      </span>
                    )}
                    {!current && enabled && (
                      <button
                        type="button"
                        onClick={() => void switchDataflowProvider(name)}
                        disabled={switching}
                        className="text-[9px] text-neon-cyan/90 font-mono uppercase bg-neon-cyan/10 px-1.5 py-0.5 rounded border border-neon-cyan/30 disabled:opacity-60"
                      >
                        {switching ? '切换中...' : '切换'}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </ConfigSection>

        <ConfigSection title="LLM 配置" icon={Cpu}>
          <div className="space-y-2">
            <label className="text-[9px] text-info-gray/50 uppercase font-bold tracking-wider">Base URL</label>
            <input className="w-full bg-bg-primary border border-border rounded px-3 py-2 text-xs text-white" value={llmConfig.base_url} onChange={(e) => setLlmConfig((prev) => ({ ...prev, base_url: e.target.value }))} />
          </div>
          <div className="space-y-2">
            <label className="text-[9px] text-info-gray/50 uppercase font-bold tracking-wider">Model</label>
            <input className="w-full bg-bg-primary border border-border rounded px-3 py-2 text-xs text-white" value={llmConfig.model} onChange={(e) => setLlmConfig((prev) => ({ ...prev, model: e.target.value }))} />
          </div>
          <div className="space-y-2">
            <label className="text-[9px] text-info-gray/50 uppercase font-bold tracking-wider">Temperature</label>
            <input
              type="number"
              min={0}
              max={2}
              step={0.1}
              className="w-full bg-bg-primary border border-border rounded px-3 py-2 text-xs text-white"
              value={llmConfig.temperature === null ? '' : llmConfig.temperature}
              onChange={(e) =>
                setLlmConfig((prev) => ({
                  ...prev,
                  temperature: toOptionalNumber(e.target.value),
                }))
              }
            />
          </div>
          <div className="space-y-2">
            <label className="text-[9px] text-info-gray/50 uppercase font-bold tracking-wider">API Key</label>
            <input type="password" className="w-full bg-bg-primary border border-border rounded px-3 py-2 text-xs text-white" value={llmConfig.api_key} onChange={(e) => setLlmConfig((prev) => ({ ...prev, api_key: e.target.value }))} />
          </div>
        </ConfigSection>

        <ConfigSection title="通知通道" icon={MessageSquare}>
          <div className="space-y-2">
            <label className="text-[9px] text-info-gray/50 uppercase font-bold tracking-wider">企业微信 Webhook</label>
            <input className="w-full bg-bg-primary border border-border rounded px-3 py-2 text-xs text-white" value={webhookUrl} onChange={(e) => setWebhookUrl(e.target.value)} />
          </div>
          <div className="space-y-2">
            <label className="text-[9px] text-info-gray/50 uppercase font-bold tracking-wider">钉钉 Secret</label>
            <input type="password" className="w-full bg-bg-primary border border-border rounded px-3 py-2 text-xs text-white" value={dingtalkSecret} onChange={(e) => setDingtalkSecret(e.target.value)} />
          </div>
          <button onClick={testNotification} className="w-full py-2 rounded border border-neon-cyan/50 text-neon-cyan hover:bg-neon-cyan/10 text-xs font-bold uppercase flex items-center justify-center gap-2" disabled={isTestingNotification}>
            {isTestingNotification ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />} 发送测试通知
          </button>
        </ConfigSection>

        <ConfigSection title="THS Bridge 控制" icon={Power}>
          <div className="p-3 bg-bg-primary/50 border border-border rounded flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="text-xs text-white">THS Bridge</div>
              <div className="text-[9px] font-mono text-info-gray/60 truncate">
                {String(bridgeState.message ?? '等待状态刷新')}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => void refreshBridgeState()}
                disabled={isRefreshingBridge}
                className="text-[9px] text-neon-cyan/90 font-mono uppercase bg-neon-cyan/10 px-1.5 py-0.5 rounded border border-neon-cyan/30 disabled:opacity-60"
              >
                {isRefreshingBridge ? '刷新中...' : '刷新'}
              </button>
              <span
                className={cn(
                  'text-[10px] font-mono uppercase',
                  bridgeStatus === 'READY'
                    ? 'text-up-green'
                    : bridgeStatus === 'STARTING' || bridgeStatus === 'STOPPING'
                      ? 'text-warn-gold'
                      : 'text-info-gray',
                )}
              >
                {bridgeStatus}
              </span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={startBridge}
              disabled={bridgeAction !== ''}
              className="w-full py-2 rounded border border-border text-white hover:border-neon-cyan text-xs font-bold uppercase flex items-center justify-center gap-2 disabled:opacity-60"
            >
              {bridgeAction === 'starting' ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Power className="h-3 w-3" />}
              启动 Bridge
            </button>
            <button
              type="button"
              onClick={stopBridge}
              disabled={bridgeAction !== ''}
              className="w-full py-2 rounded border border-down-red/50 text-down-red hover:bg-down-red/10 text-xs font-bold uppercase flex items-center justify-center gap-2 disabled:opacity-60"
            >
              {bridgeAction === 'stopping' ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Power className="h-3 w-3" />}
              停止 Bridge
            </button>
          </div>

          <div className="text-[10px] font-mono text-info-gray/60">
            host: {String(bridgeState.host ?? '--')} : {String(bridgeState.port ?? '--')} / pid: {String(bridgeState.pid ?? '--')}
          </div>
          {bridgeNotice && <div className="text-[10px] text-up-green">{bridgeNotice}</div>}
          {bridgeError && <div className="text-[10px] text-down-red">{bridgeError}</div>}
        </ConfigSection>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={isSaving}
          className="px-6 py-2 rounded bg-neon-cyan text-black font-bold text-xs uppercase hover:bg-neon-cyan/90 disabled:opacity-70 flex items-center gap-2"
        >
          {isSaving ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />} 保存配置
        </button>

        {showSuccess && (
          <div className="text-up-green text-xs flex items-center gap-1">
            <CheckCircle2 className="h-3 w-3" /> 配置已保存
          </div>
        )}
        {showError && (
          <div className="text-down-red text-xs flex items-center gap-1">
            <AlertCircle className="h-3 w-3" /> {errorMessage}
          </div>
        )}
      </div>
    </div>
  );
};

export default SystemConfig;
