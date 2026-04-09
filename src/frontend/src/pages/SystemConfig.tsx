import React, { useState, useEffect } from 'react';
import { 
  Database, 
  Send, 
  Settings, 
  Zap, 
  CheckCircle2, 
  AlertCircle, 
  Globe, 
  MessageSquare, 
  Cpu,
  Power,
  Loader2,
  RefreshCw
} from 'lucide-react';
import { cn } from '../lib/utils';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

interface ConfigSectionProps {
  title: string;
  icon: React.ElementType;
  children: React.ReactNode;
}

const ConfigSection: React.FC<ConfigSectionProps> = ({ title, icon: Icon, children }) => (
  <div className="bg-bg-card/30 border border-border rounded-lg overflow-hidden transition-all hover:bg-bg-card/50">
    <div className="bg-bg-card/50 border-b border-border p-4 flex items-center gap-3">
      <Icon className="h-4 w-4 text-neon-cyan" />
      <h3 className="text-[10px] font-orbitron text-white tracking-[0.2em] uppercase">{title}</h3>
    </div>
    <div className="p-5 space-y-4">
      {children}
    </div>
  </div>
);

export const SystemConfig: React.FC = () => {
  const [mcpStatus, setMcpStatus] = useState<'IDLE' | 'STARTING' | 'RUNNING'>('IDLE');
  const [tushareStatus, setTushareStatus] = useState<'NONE' | 'TESTING' | 'OK' | 'ERROR'>('NONE');
  const [isSaving, setIsSaving] = useState(false);
  const [isTestingNotification, setIsTestingNotification] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);
  const [showError, setShowError] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  // Form State
  const [tushareToken, setTushareToken] = useState('••••••••••••••••••••••••••••••••');
  const [llmConfig, setLlmConfig] = useState({
    base_url: 'https://api.openai.com/v1',
    model: 'gpt-4o-2024-05-13',
    temperature: 0.7,
    api_key: '••••••••••••••••'
  });
  const [webhookUrl, setWebhookUrl] = useState('');
  const [dingtalkSecret, setDingtalkSecret] = useState('••••••••••••••••••••••••••••••••');

  useEffect(() => {
    const fetchConfigs = async () => {
      try {
        const [sysRes, llmRes] = await Promise.all([
          fetch(`${API_BASE}/api/system/config`),
          fetch(`${API_BASE}/api/system/llm-config`)
        ]);
        
        if (sysRes.ok) {
          const sysData = await sysRes.json();
          if (sysData.data) {
            setTushareToken(sysData.data.tushare_token || '••••••••••••••••••••••••••••••••');
            setWebhookUrl(sysData.data.wechat_webhook || '');
            setDingtalkSecret(sysData.data.dingtalk_secret || '••••••••••••••••••••••••••••••••');
          }
        }
        
        if (llmRes.ok) {
          const llmData = await llmRes.json();
          const config = llmData.data || llmData;
          setLlmConfig({
            base_url: config.base_url || 'https://api.openai.com/v1',
            model: config.model || 'gpt-4o-2024-05-13',
            temperature: config.temperature ?? 0.7,
            api_key: config.api_key || '••••••••••••••••'
          });
        }
      } catch (e) {
        console.warn('Failed to fetch system configs, using defaults.');
      }
    };
    fetchConfigs();
  }, []);

  const testTushare = async (e: React.MouseEvent) => {
    e.preventDefault();
    setTushareStatus('TESTING');
    try {
      const response = await fetch(`${API_BASE}/api/system/llm/config/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          type: 'tushare', 
          token: tushareToken.includes('*') || tushareToken.includes('•') ? undefined : tushareToken 
        })
      });
      if (response.ok) {
        setTushareStatus('OK');
      } else {
        setTushareStatus('ERROR');
        const errorData = await response.json();
        setErrorMessage(errorData.message || 'Tushare test failed.');
        setShowError(true);
        setTimeout(() => setShowError(false), 5000);
      }
    } catch (e: any) {
      console.error(e);
      setTushareStatus('ERROR');
      setErrorMessage(e.message || 'Tushare connection error.');
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
      const response = await fetch(`${API_BASE}/api/system/notification/test/wechat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          webhook_url: webhookUrl, 
          channel: 'wechat' 
        })
      });
      
      const resData = await response.json();
      if (!response.ok) {
        throw new Error(resData.message || 'WeChat notification test failed.');
      }
      
      setShowSuccess(true);
      setTimeout(() => setShowSuccess(false), 3000);
    } catch (e: any) {
      console.error(e);
      setErrorMessage(e.message || 'Notification test failed.');
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
      // 准备 LLM 配置数据，过滤掩码值
      const finalLlmConfig = {
        ...llmConfig,
        api_key: (llmConfig.api_key.includes('*') || llmConfig.api_key.includes('•')) ? "" : llmConfig.api_key,
        retain_api_key: (llmConfig.api_key.includes('*') || llmConfig.api_key.includes('•'))
      };

      const [sysRes, llmRes] = await Promise.all([
        fetch(`${API_BASE}/api/system/config`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            tushare_token: tushareToken.includes('*') || tushareToken.includes('•') ? undefined : tushareToken,
            wechat_webhook: webhookUrl,
            dingtalk_secret: dingtalkSecret.includes('*') || dingtalkSecret.includes('•') ? undefined : dingtalkSecret
          })
        }),
        fetch(`${API_BASE}/api/system/llm-config`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(finalLlmConfig)
        })
      ]);
      
      if (!sysRes.ok || !llmRes.ok) {
        const sysErr = !sysRes.ok ? await sysRes.json() : null;
        const llmErr = !llmRes.ok ? await llmRes.json() : null;
        throw new Error(llmErr?.message || sysErr?.message || 'Some configurations failed to save.');
      }
      
      setShowSuccess(true);
      setTimeout(() => setShowSuccess(false), 3000);
    } catch (e: any) {
      console.error(e);
      setErrorMessage(e.message || 'Failed to save configuration.');
      setShowError(true);
      setTimeout(() => setShowError(false), 5000);
    } finally {
      setIsSaving(false);
    }
  };

  const startMcp = (e: React.MouseEvent) => {
    e.preventDefault();
    setMcpStatus('STARTING');
    setTimeout(() => setMcpStatus('RUNNING'), 2000);
  };

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <header className="mb-12">
        <h1 className="text-3xl font-orbitron font-extrabold text-white tracking-widest flex items-center gap-4">
          <Settings className="text-neon-cyan h-8 w-8 animate-pulse" />
          系统配置 <span className="text-neon-cyan/50 text-[10px] font-mono tracking-normal ml-4 border border-neon-cyan/30 px-2 py-0.5 rounded uppercase">V1.0.4-稳定版</span>
        </h1>
        <p className="text-info-gray/60 text-xs mt-2 uppercase tracking-[0.2em] font-light">全局架构、数据流与通信协议管理</p>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        {/* Data Source Configuration */}
        <ConfigSection title="数据源协议" icon={Database}>
          <div className="space-y-4">
            <div className="p-3 bg-bg-primary/50 border border-border rounded flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Globe className="h-4 w-4 text-up-green" />
                <span className="text-xs font-mono text-white">AkShare (Standard)</span>
              </div>
              <span className="text-[9px] text-up-green/80 font-mono uppercase bg-up-green/5 px-1.5 py-0.5 rounded border border-up-green/20">已激活</span>
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
                  onClick={(e) => testTushare(e)}
                  className={cn(
                    "px-4 py-2 rounded text-[10px] font-mono border transition-all uppercase flex items-center gap-2",
                    tushareStatus === 'OK' ? "bg-up-green/10 border-up-green text-up-green" : tushareStatus === 'ERROR' ? "bg-down-red/10 border-down-red text-down-red" : "bg-neon-cyan/10 border-neon-cyan text-neon-cyan hover:bg-neon-cyan hover:text-black"
                  )}
                >
                  {tushareStatus === 'TESTING' ? <Zap className="h-3 w-3 animate-spin" /> : tushareStatus === 'OK' ? <CheckCircle2 className="h-3 w-3" /> : <Zap className="h-3 w-3" />}
                  {tushareStatus === 'TESTING' ? '测试中...' : tushareStatus === 'OK' ? '已连接' : tushareStatus === 'ERROR' ? '测试失败' : '测试'}
                </button>
              </div>
            </div>

            <div className="p-3 bg-bg-primary/50 border border-border rounded flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Globe className="h-4 w-4 text-info-gray/40" />
                <span className="text-xs font-mono text-info-gray/60">BaoStock (Optional)</span>
              </div>
              <span className="text-[9px] text-info-gray/40 font-mono uppercase bg-bg-hover px-1.5 py-0.5 rounded border border-border">已禁用</span>
            </div>
          </div>
        </ConfigSection>

        {/* Trading Channels */}
        <ConfigSection title="执行通道" icon={Zap}>
          <div className="space-y-4">
            <div className="space-y-3 p-4 bg-bg-primary/50 border border-border rounded">
              <div className="flex items-center justify-between">
                <span className="text-xs font-mono text-white">THS IPC (A-Share)</span>
                <div className="h-4 w-8 bg-up-green/20 border border-up-green/50 rounded-full flex items-center justify-end px-1 cursor-pointer">
                  <div className="h-2 w-2 rounded-full bg-up-green" />
                </div>
              </div>
              <div className="space-y-2">
                <label className="text-[9px] text-info-gray/50 uppercase font-mono">主窗口句柄 (HWND)</label>
                <input type="text" className="w-full bg-bg-primary border border-border/50 rounded px-2 py-1.5 text-xs text-neon-cyan font-mono" defaultValue="0x002A14" />
              </div>
            </div>

            <div className="space-y-3 p-4 bg-bg-primary/50 border border-border rounded opacity-60 grayscale">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-info-gray">MiniQMT 集成</span>
                  <span className="text-[8px] bg-warn-gold/20 text-warn-gold px-1.5 py-0.5 rounded border border-warn-gold/30">暂停</span>
                </div>
                <div className="h-4 w-8 bg-bg-hover border border-border rounded-full flex items-center justify-start px-1 cursor-not-allowed">
                  <div className="h-2 w-2 rounded-full bg-info-gray/30" />
                </div>
              </div>
              <div className="space-y-2">
                <label className="text-[9px] text-info-gray/50 uppercase font-mono">会话标识符</label>
                <input type="text" disabled className="w-full bg-bg-primary/30 border border-border/20 rounded px-2 py-1.5 text-xs text-info-gray/30 font-mono" placeholder="WAITING_AUTH..." />
              </div>
            </div>
          </div>
        </ConfigSection>

        {/* MCP Server Config */}
        <ConfigSection title="MCP 协议核心" icon={Cpu}>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <label className="text-[9px] text-info-gray/50 uppercase font-mono tracking-wider">主机接口</label>
                <input type="text" className="w-full bg-bg-primary border border-border rounded px-3 py-2 text-xs text-white outline-none font-mono" defaultValue="localhost" />
              </div>
              <div className="space-y-2">
                <label className="text-[9px] text-info-gray/50 uppercase font-mono tracking-wider">端口</label>
                <input type="text" className="w-full bg-bg-primary border border-border rounded px-3 py-2 text-xs text-white outline-none font-mono" defaultValue="8080" />
              </div>
            </div>
            
            <button 
              type="button"
              onClick={(e) => startMcp(e)}
              className={cn(
                "w-full py-3 rounded text-[10px] font-orbitron tracking-widest uppercase transition-all flex items-center justify-center gap-3",
                mcpStatus === 'RUNNING' 
                  ? "bg-up-green/10 border border-up-green/50 text-up-green shadow-[0_0_15px_rgba(0,255,157,0.1)]" 
                  : "bg-neon-cyan/10 border border-neon-cyan/50 text-neon-cyan hover:bg-neon-cyan hover:text-black"
              )}
            >
              <Power className={cn("h-3 w-3", mcpStatus === 'STARTING' && "animate-spin")} />
              {mcpStatus === 'RUNNING' ? 'MCP 核心运行中' : mcpStatus === 'STARTING' ? '协议初始化中...' : '启动 MCP 服务'}
            </button>
            
            <div className="flex items-center gap-2 text-[9px] font-mono text-info-gray/40">
              <div className={cn("h-1.5 w-1.5 rounded-full", mcpStatus === 'RUNNING' ? "bg-up-green animate-pulse" : "bg-bg-hover")} />
              状态: {mcpStatus} (中继系统 V2)
            </div>
          </div>
        </ConfigSection>

        {/* Messaging Configuration */}
        <ConfigSection title="告警与消息" icon={MessageSquare}>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-[9px] text-info-gray/50 uppercase font-bold tracking-wider">企业微信 Webhook</label>
              <input 
                type="text" 
                className="w-full bg-bg-primary border border-border rounded px-3 py-2 text-xs text-white outline-none focus:border-neon-cyan transition-colors" 
                placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..." 
                value={webhookUrl}
                onChange={(e) => setWebhookUrl(e.target.value)}
              />
            </div>
            
            <div className="space-y-2">
              <label className="text-[9px] text-info-gray/50 uppercase font-bold tracking-wider">钉钉密钥</label>
              <input 
                type="password" 
                className="w-full bg-bg-primary border border-border rounded px-3 py-2 text-xs text-white outline-none focus:border-neon-cyan transition-colors" 
                value={dingtalkSecret}
                onChange={(e) => setDingtalkSecret(e.target.value)}
              />
            </div>

            <button 
              type="button"
              onClick={(e) => testNotification(e)}
              disabled={isTestingNotification}
              className="w-full flex items-center justify-center gap-2 py-2.5 rounded text-[10px] font-mono border border-border bg-bg-primary hover:bg-bg-hover hover:border-neon-cyan/30 text-info-gray transition-all uppercase"
            >
              {isTestingNotification ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}
              测试通知通道
            </button>
          </div>
        </ConfigSection>

        {/* LLM Model Configuration */}
        <div className="md:col-span-2">
          <ConfigSection title="LLM 智能引擎" icon={Cpu}>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
              <div className="space-y-2">
                <label className="text-[9px] text-info-gray/50 uppercase font-bold tracking-wider">API 基准地址</label>
                <input 
                  type="text" 
                  className="w-full bg-bg-primary border border-border rounded px-3 py-2 text-xs text-white outline-none font-mono focus:border-neon-cyan transition-colors" 
                  value={llmConfig.base_url}
                  onChange={(e) => setLlmConfig({ ...llmConfig, base_url: e.target.value })}
                  placeholder="https://api.openai.com/v1"
                />
              </div>
              <div className="space-y-2">
                <label className="text-[9px] text-info-gray/50 uppercase font-bold tracking-wider">API 密钥 (API Key)</label>
                <input 
                  type="password" 
                  className="w-full bg-bg-primary border border-border rounded px-3 py-2 text-xs text-white outline-none font-mono focus:border-neon-cyan transition-colors" 
                  value={llmConfig.api_key}
                  onChange={(e) => setLlmConfig({ ...llmConfig, api_key: e.target.value })}
                  placeholder="sk-••••••••••••••••"
                />
              </div>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="space-y-2">
                <label className="text-[9px] text-info-gray/50 uppercase font-bold tracking-wider">当前模型 (Model Name)</label>
                <input 
                  type="text" 
                  className="w-full bg-bg-primary border border-border rounded px-3 py-2 text-xs text-white outline-none font-mono focus:border-neon-cyan transition-colors" 
                  value={llmConfig.model}
                  onChange={(e) => setLlmConfig({ ...llmConfig, model: e.target.value })}
                  placeholder="gpt-4o"
                />
              </div>
              <div className="space-y-2">
                <div className="flex justify-between items-center">
                  <label className="text-[9px] text-info-gray/50 uppercase font-bold tracking-wider">采样温度 (Temperature: {llmConfig.temperature})</label>
                  <span className={cn(
                    "text-[10px] font-mono",
                    llmConfig.temperature > 1.2 ? "text-warn-gold" : "text-neon-cyan"
                  )}>{llmConfig.temperature.toFixed(1)}</span>
                </div>
                <input 
                  type="range" min="0" max="2" step="0.1" 
                  className="w-full accent-neon-cyan bg-bg-primary cursor-pointer h-1.5 rounded-full appearance-none" 
                  value={llmConfig.temperature}
                  onChange={(e) => setLlmConfig({ ...llmConfig, temperature: parseFloat(e.target.value) })}
                />
                <div className="flex justify-between text-[8px] font-mono text-info-gray/40">
                  <span>精确 (0.0)</span>
                  <span>平衡 (1.0)</span>
                  <span>创造性 (2.0)</span>
                </div>
              </div>
            </div>
            
            <div className="pt-4 border-t border-border mt-6">
              <div className="flex items-center gap-2">
                <AlertCircle className="h-3 w-3 text-warn-gold" />
                <p className="text-[10px] text-info-gray/60 italic font-light">警告: 修改 LLM 设置可能会影响实盘过程中的推理稳定性和响应延迟。Temperature 高于 1.0 时请谨慎使用。</p>
              </div>
            </div>
          </ConfigSection>
        </div>
      </div>

      <footer className="flex justify-end items-center gap-4 pb-12">
        {showSuccess && (
          <div className="flex items-center gap-2 text-up-green animate-in fade-in slide-in-from-right-2">
            <CheckCircle2 className="h-4 w-4" />
            <span className="text-xs font-bold font-orbitron uppercase tracking-widest">保存成功 / SUCCESSFUL</span>
          </div>
        )}
        {showError && (
          <div className="flex items-center gap-2 text-down-red animate-in fade-in slide-in-from-right-2">
            <AlertCircle className="h-4 w-4" />
            <span className="text-xs font-bold font-orbitron uppercase tracking-widest truncate max-w-[300px]">{errorMessage || '保存失败 / FAILED'}</span>
          </div>
        )}
        <button 
          type="button"
          onClick={() => window.location.reload()}
          className="px-8 py-3 rounded border border-border text-[10px] font-orbitron tracking-widest text-info-gray hover:text-white transition-all uppercase flex items-center gap-2"
        >
          <RefreshCw className="h-3 w-3" />
          重置 / 刷新
        </button>
        <button 
          type="button"
          onClick={(e) => handleSave(e)}
          disabled={isSaving}
          className="px-8 py-3 rounded bg-neon-cyan border border-neon-cyan text-black text-[10px] font-orbitron tracking-widest font-bold hover:shadow-[0_0_20px_rgba(0,240,255,0.4)] transition-all uppercase flex items-center gap-2"
        >
          {isSaving ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
          {isSaving ? '保存中...' : '保存配置'}
        </button>
      </footer>
    </div>
  );
};

export default SystemConfig;
