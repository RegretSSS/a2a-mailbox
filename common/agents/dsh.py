SPEC = {
    "cli": "dsh",
    "proc_names": ("dsh",),
    "delivery_kind": "rpc-inbox",
    "notes": "web host /api session/prompt 入队(running=steer 打断, idle=queue 唤醒); token 换 cookie 30 天缓存; 身份=A2A_AGENT_ID+A2A_CLI 显式 env(常驻 host 无 pane 语义, A2A_PANELESS=1); 回执=mail_ack, 入队即送达; 缺席滞留重试不降级",
}
