/* ===== app.js — 完整前端逻辑（迁移自旧 static/index.html）===== */
// 主题/语言防闪烁已由 base.html 内联脚本处理
var I18N={
'zh-CN':{nav_home:'首页',nav_generate:'生图',nav_batch:'批量',nav_history:'历史',nav_status:'状态',nav_settings:'设置',preset:'预设',save_preset:'保存当前为预设',recent:'最近生成',neg_add:'＋ 负向提示词',neg_hide:'− 收起负向提示词',btn_generate:'▶ 生成',btn_advanced:'⚙ 高级参数',btn_gallery:'▦ 图片展示',btn_history:'◷ 历史记录',btn_batch:'▤ 批量模式',btn_presets:'▣ 预设管理',btn_share:'分享',btn_clear:'清空',btn_copy:'复制',btn_free_vram:'释放显存',btn_restore_default:'恢复默认',btn_done:'完成',btn_generate_batch:'▶ 生成批次',btn_cancel:'取消',batch_prompt_file:'Prompt 文件',batch_param_grid:'参数网格',search_placeholder:'搜索',phase_connecting:'连接中',phase_loading_workflow:'加载工作流',phase_engine_ready:'引擎就绪',phase_patching:'打补丁',phase_queuing:'排队中',phase_sampling:'采样中',phase_executing:'执行节点',phase_image_saved:'已保存',phase_completed:'完成',phase_cancelling:'取消中',share_no_output:'暂无输出可分享',share_copied:'已复制图片链接与提示词',share_failed:'分享失败',g_all:'全部',top_theme:'主题',top_color:'颜色',top_font:'字体',top_about:'关于',top_settings:'设置',top_model:'模型',top_lang:'语言',drawer_gallery:'图片展示',drawer_gallery_hint:'顶抽屉 · 点击卡片弹出悬浮查看器',drawer_history:'历史记录',drawer_history_hint:'搜索 / seed',drawer_batch:'批量模式',drawer_batch_hint:'底抽屉 · Prompt 文件 / 参数网格',drawer_settings:'设置',drawer_settings_hint:'顶抽屉 · 全局配置',drawer_status:'系统状态',drawer_status_hint:'顶抽屉 · 点击底栏状态区展开',drawer_about:'关于 · 项目介绍',drawer_about_hint:'顶抽屉 · 应用内板块',tagline_pre:'让每一句心语，',tagline_em:'化作光影',sub_tagline:'输入你的创意描述，AI 将为你生成独一无二的图像',snap_engine:'引擎',snap_res:'分辨率',snap_est:'预计',snap_imgs:'张',est_line:'预计生成 {total} 张 = 1 Prompt × {n} batch',warn_500:'⚠ 超过 500 张：建议夜间生成，预计约 40min（RTX 4090 估算）',warn_5000:'⚠ 超过 5000 张：自动断点续跑（每 100 张 checkpoint），点击「生成」需二次确认',type_original:'原图',type_upscaled:'超分',type_compare:'对比图',st_completed:'完成',st_failed:'失败',st_cancelled:'已取消',st_processing:'进行中',st_pending:'排队中',char_count:'{n} 字符 · ≈{t} token',th_preview:'预览',th_prompt:'Prompt',th_status:'状态',th_actions:'操作',hist_status_all:'状态',hist_purge:'批量删除',hist_clear:'清除',btn_prev_page:'‹ 上一页',btn_next_page:'下一页 ›',hist_total:'共 {n} 条',hist_page:'第 {p}/{tp} 页',st_interrupted:'已中断',drawer_adv:'高级参数',drawer_adv_hint:'22 项 · 改动即时生效',drawer_presets:'预设管理',drawer_presets_hint:'与生图页联动',set_engine_model:'引擎与模型',set_default_engine:'默认引擎',set_workflow_dir:'工作流目录',set_model_mode:'模型源模式',set_seedvr2_dir:'SeedVR2 模型',set_scan:'完整资源扫描',set_scan_hint:'待扫描',set_runtime:'运行',set_heartbeat:'心跳轮询',set_hb_30:'每 30s',set_hb_60:'每 60s',set_spawn:'自动拉起后端',set_spawn_on:'开启（进程自动恢复）',set_spawn_off:'关闭',set_lb:'负载均衡',set_lb_local:'优先本地',set_lb_rr:'轮询',set_lb_lc:'最少连接',set_retention:'保留策略',set_hist_ret:'历史保留',set_ret_forever:'永久',set_config:'配置',set_export_json:'导出配置 JSON',set_import_json:'导入配置 JSON',about_sub:'Z-Image Turbo 图像生成平台',about_desc:'面向本地 AI 图像生成的工作台：Z-Image-Turbo 原生引擎进程内推理，LoRA 六层叠加、SeedVR2 超分、Eses 双图对比与显存预留，以对话式主界面屏蔽工作流复杂度。',about_author:'作者',about_version:'当前版本',about_license:'协议',about_github:'GitHub 仓库',feat_native:'原生引擎',feat_native_sub:'Z-Image-Turbo，进程内推理',feat_lora:'六层 LoRA',feat_lora_sub:'串联叠加 id=16→21，禁用自动重连',feat_seedvr2:'SeedVR2 超分',feat_seedvr2_sub:'ema_vae + 3B DiT，多档最短边',feat_compare:'双图对比',feat_compare_sub:'Eses h/v/s 拼接，直观比对',feat_vram:'显存预留',feat_vram_sub:'ReservedVRAM 保护生成稳定',feat_local:'本地运行',feat_local_sub:'进程内原生引擎，数据不出机器',about_db_note:'© 2024-2026 ReSerendipity · Apache 2.0 开源 · 项目仓库与社交账号均已上线，欢迎 Star 与关注。',batch_drop_title:'拖拽或点击上传 Prompt 文件',batch_drop_sub:'支持 .txt / .csv · 每行一个 Prompt · 空行自动过滤 · 跨文件去重',batch_no_files:'未添加文件',batch_per_line:'每行 batch',batch_mult_16:'16 倍数',batch_grid_hint:'勾选的参数值做笛卡尔积展开为参数组合；提交时随 base_config 一起发送给后端。',batch_est_title:'批次估算',batch_grid_combo:'参数网格组合',batch_file_stat:'{n} 个 · {l} 行',batch_groups_val:'{n} 组',batch_est_line:'预计生成 <b>{t}</b> 张 = {l} 行 × {g} 组 × batch {b}',batch_queue_title:'任务队列',batch_line_n:'{n} 行',batch_parsed:'已解析',batch_remove:'移除',batch_none:'暂无批量任务',batch_querying:'查询批次 {id}…',batch_title_line:'batch {id} · 共 {n} 个任务',batch_status_line:'{c} 完成 · {p} 进行中 · {q} 排队 · {f} 失败 · {x} 取消',batch_not_found:'批次不存在或已过期',batch_query_fail:'查询失败',batch_submit_fail:'批量提交失败: {e}',preset_multi:'多选',select_all:'全选',cancel_select_all:'取消全选',sel_count:'已选 {n}',preset_back:'← 返回列表',preset_edit_title:'编辑预设',preset_name:'名称',preset_desc:'描述',preset_engine:'引擎',preset_save:'保存预设',preset_new:'＋ 新建预设',presets_empty:'暂无预设，点击「＋ 新建预设」创建',unnamed:'未命名',btn_apply:'应用',btn_edit:'编辑',btn_delete:'删除',load_failed:'加载失败',btn_got_it:'知道了',preset_del_confirm:'删除预设「{n}」？此操作不可恢复。',preset_del_fail:'删除失败: {e}',preset_del_confirm_batch:'将批量删除 {n} 个预设，此操作不可恢复。确认？',presets_deleted:'已删除 {n} 个预设',preset_applied:'已应用预设：{n}',preset_apply_fail:'应用失败: {e}',preset_updated:'预设已更新',preset_saved_ok:'预设已保存',save_failed:'保存失败: {e}',param_json:'参数 JSON：',preset_default_name:'预设 {n}',hist_detail_title:'任务详情',dd_dim:'尺寸 · seed',dd_time:'耗时 · 时间',dd_redraw:'用相同参数重绘',dd_save_preset:'保存为预设',dd_zip:'下载 ZIP',out_count:'{n} 张输出',no_preview:'无预览',no_prompt:'(无提示词)',viewer_title:'图片查看',expand:'展开',collapse:'收起',queue_idle:'队列空闲',queue_cancel:'取消当前',loading:'加载中…',no_images:'暂无图片',gen_result:'生成结果',stat_gpu:'GPU 显存',stat_mem:'系统内存',stat_disk:'磁盘 outputs/',stat_resources:'引擎与资源',stat_lora:'LoRA 资源',stat_refresh:'刷新状态',adv_basic:'基础参数',adv_items_8:'8 项',adv_cfg:'cfg（蒸馏推荐 1.0）',adv_width:'width（16 倍数）',adv_height:'height（16 倍数）',adv_seed:'seed（-1 = 随机）',adv_lora:'LoRA 叠加',adv_lora_chain:'6 层串联',adv_strength:'强度',adv_ready:'已接入',adv_enable_seedvr2:'启用 SeedVR2 超分',adv_upscale_res:'超分分辨率（最短边）',adv_color_corr:'色彩校正',adv_upscale_seed:'upscale_seed（独立）',adv_compare:'对比 + 显存预留',adv_eses:'Eses 双图对比（原图 vs 对比图）',adv_axis:'轴',adv_vram:'ReservedVRAM 显存预留',adv_output:'输出设置',adv_out_format:'输出格式',adv_prefix:'文件名前缀模板',adv_est_hint:'估算与阈值警告显示在主界面操作行下方',adv_lora_warn:'⚠ 默认 LoRA 已在磁盘找到；缺失将自动 _disabled + 黄提示。'},
'zh-TW':{nav_home:'首頁',nav_generate:'生圖',nav_batch:'批量',nav_history:'歷史',nav_status:'狀態',nav_settings:'設定',preset:'預設',save_preset:'儲存目前為預設',recent:'最近生成',neg_add:'＋ 負向提示詞',neg_hide:'− 收起負向提示詞',btn_generate:'▶ 生成',btn_advanced:'⚙ 進階參數',btn_gallery:'▦ 圖片展示',btn_history:'◷ 歷史記錄',btn_batch:'▤ 批量模式',btn_presets:'▣ 預設管理',btn_share:'分享',btn_clear:'清空',btn_copy:'複製',btn_free_vram:'釋放顯存',btn_restore_default:'恢復預設',btn_done:'完成',btn_generate_batch:'▶ 生成批次',btn_cancel:'取消',batch_prompt_file:'Prompt 檔案',batch_param_grid:'參數網格',search_placeholder:'搜尋',phase_connecting:'連接中',phase_loading_workflow:'載入工作流程',phase_engine_ready:'引擎就緒',phase_patching:'修補中',phase_queuing:'排隊中',phase_sampling:'採樣中',phase_executing:'執行節點',phase_image_saved:'已儲存',phase_completed:'完成',phase_cancelling:'取消中',share_no_output:'暫無輸出可分享',share_copied:'已複製圖片連結與提示詞',share_failed:'分享失敗',g_all:'全部',top_theme:'主題',top_color:'顏色',top_font:'字型',top_about:'關於',top_settings:'設定',top_model:'模型',top_lang:'語言',drawer_gallery:'圖片展示',drawer_gallery_hint:'頂抽屜 · 點擊卡片彈出浮動檢視器',drawer_history:'歷史記錄',drawer_history_hint:'搜尋 / seed',drawer_batch:'批量模式',drawer_batch_hint:'底抽屜 · Prompt 檔案 / 參數網格',drawer_settings:'設定',drawer_settings_hint:'頂抽屜 · 全域設定',drawer_status:'系統狀態',drawer_status_hint:'頂抽屜 · 點擊底欄狀態區展開',drawer_about:'關於 · 專案介紹',drawer_about_hint:'頂抽屜 · 應用內板塊',tagline_pre:'讓每一句心語，',tagline_em:'化作光影',sub_tagline:'輸入你的創意描述，AI 將為你生成獨一無二的圖像',snap_engine:'引擎',snap_res:'解析度',snap_est:'預計',snap_imgs:'張',est_line:'預計生成 {total} 張 = 1 Prompt × {n} batch',warn_500:'⚠ 超過 500 張：建議夜間生成，預計約 40min（RTX 4090 估算）',warn_5000:'⚠ 超過 5000 張：自動斷點續跑（每 100 張 checkpoint），點擊「生成」需二次確認',type_original:'原圖',type_upscaled:'超分',type_compare:'對比圖',st_completed:'完成',st_failed:'失敗',st_cancelled:'已取消',st_processing:'進行中',st_pending:'排隊中',char_count:'{n} 字元 · ≈{t} token',th_preview:'預覽',th_prompt:'Prompt',th_status:'狀態',th_actions:'操作',hist_status_all:'狀態',hist_purge:'批量刪除',hist_clear:'清除',btn_prev_page:'‹ 上一頁',btn_next_page:'下一頁 ›',hist_total:'共 {n} 條',hist_page:'第 {p}/{tp} 頁',st_interrupted:'已中斷',drawer_adv:'進階參數',drawer_adv_hint:'22 項 · 改動即時生效',drawer_presets:'預設管理',drawer_presets_hint:'與生圖頁連動',set_engine_model:'引擎與模型',set_default_engine:'預設引擎',set_workflow_dir:'工作流目錄',set_model_mode:'模型源模式',set_seedvr2_dir:'SeedVR2 模型',set_scan:'完整資源掃描',set_scan_hint:'待掃描',set_runtime:'執行',set_heartbeat:'心跳輪詢',set_hb_30:'每 30s',set_hb_60:'每 60s',set_spawn:'自動拉起後端',set_spawn_on:'開啟（進程自動恢復）',set_spawn_off:'關閉',set_lb:'負載均衡',set_lb_local:'優先本地',set_lb_rr:'輪詢',set_lb_lc:'最少連接',set_retention:'保留策略',set_hist_ret:'歷史保留',set_ret_forever:'永久',set_config:'設定',set_export_json:'匯出設定 JSON',set_import_json:'匯入設定 JSON',about_sub:'Z-Image Turbo 圖像生成平台',about_desc:'面向本地 AI 圖像生成的工作台：Z-Image-Turbo 原生引擎進程內推理，LoRA 六層疊加、SeedVR2 超分、Eses 雙圖對比與顯存預留，以對話式主介面屏蔽工作流複雜度。',about_author:'作者',about_version:'目前版本',about_license:'協議',about_github:'GitHub 倉庫',feat_native:'原生引擎',feat_native_sub:'Z-Image-Turbo，進程內推理',feat_lora:'六層 LoRA',feat_lora_sub:'串聯疊加 id=16→21，停用自動重連',feat_seedvr2:'SeedVR2 超分',feat_seedvr2_sub:'ema_vae + 3B DiT，多檔最短邊',feat_compare:'雙圖對比',feat_compare_sub:'Eses h/v/s 拼接，直觀比對',feat_vram:'顯存預留',feat_vram_sub:'ReservedVRAM 保護生成穩定',feat_local:'本地運行',feat_local_sub:'進程內原生引擎，數據不出機器',about_db_note:'© 2024-2026 ReSerendipity · Apache 2.0 開源 · 專案倉庫與社交帳號均已上線，歡迎 Star 與關注。',batch_drop_title:'拖拽或點擊上傳 Prompt 檔案',batch_drop_sub:'支援 .txt / .csv · 每行一個 Prompt · 空行自動過濾 · 跨檔案去重',batch_no_files:'未添加檔案',batch_per_line:'每行 batch',batch_mult_16:'16 倍數',batch_grid_hint:'勾選的參數值做笛卡爾積展開為參數組合；提交時隨 base_config 一起發送給後端。',batch_est_title:'批次估算',batch_grid_combo:'參數網格組合',batch_file_stat:'{n} 個 · {l} 行',batch_groups_val:'{n} 組',batch_est_line:'預計生成 <b>{t}</b> 張 = {l} 行 × {g} 組 × batch {b}',batch_queue_title:'任務佇列',batch_line_n:'{n} 行',batch_parsed:'已解析',batch_remove:'移除',batch_none:'暫無批量任務',batch_querying:'查詢批次 {id}…',batch_title_line:'batch {id} · 共 {n} 個任務',batch_status_line:'{c} 完成 · {p} 進行中 · {q} 排隊 · {f} 失敗 · {x} 取消',batch_not_found:'批次不存在或已過期',batch_query_fail:'查詢失敗',batch_submit_fail:'批量提交失敗: {e}',preset_multi:'多選',select_all:'全選',cancel_select_all:'取消全選',sel_count:'已選 {n}',preset_back:'← 返回列表',preset_edit_title:'編輯預設',preset_name:'名稱',preset_desc:'描述',preset_engine:'引擎',preset_save:'儲存預設',preset_new:'＋ 新建預設',presets_empty:'暫無預設，點擊「＋ 新建預設」建立',unnamed:'未命名',btn_apply:'套用',btn_edit:'編輯',btn_delete:'刪除',load_failed:'載入失敗',btn_got_it:'知道了',preset_del_confirm:'刪除預設「{n}」？此操作不可恢復。',preset_del_fail:'刪除失敗: {e}',preset_del_confirm_batch:'將批量刪除 {n} 個預設，此操作不可恢復。確認？',presets_deleted:'已刪除 {n} 個預設',preset_applied:'已套用預設：{n}',preset_apply_fail:'套用失敗: {e}',preset_updated:'預設已更新',preset_saved_ok:'預設已儲存',save_failed:'儲存失敗: {e}',param_json:'參數 JSON：',preset_default_name:'預設 {n}',hist_detail_title:'任務詳情',dd_dim:'尺寸 · seed',dd_time:'耗時 · 時間',dd_redraw:'用相同參數重繪',dd_save_preset:'儲存為預設',dd_zip:'下載 ZIP',out_count:'{n} 張輸出',no_preview:'無預覽',no_prompt:'(無提示詞)',viewer_title:'圖片查看',expand:'展開',collapse:'收起',queue_idle:'佇列空閒',queue_cancel:'取消目前',loading:'載入中…',no_images:'暫無圖片',gen_result:'生成結果',stat_gpu:'GPU 顯存',stat_mem:'系統記憶體',stat_disk:'磁碟 outputs/',stat_resources:'引擎與資源',stat_lora:'LoRA 資源',stat_refresh:'重新整理狀態',adv_basic:'基礎參數',adv_items_8:'8 項',adv_cfg:'cfg（蒸餾推薦 1.0）',adv_width:'width（16 倍數）',adv_height:'height（16 倍數）',adv_seed:'seed（-1 = 隨機）',adv_lora:'LoRA 疊加',adv_lora_chain:'6 層串聯',adv_strength:'強度',adv_ready:'已接入',adv_enable_seedvr2:'啟用 SeedVR2 超分',adv_upscale_res:'超分解析度（最短邊）',adv_color_corr:'色彩校正',adv_upscale_seed:'upscale_seed（獨立）',adv_compare:'對比 + 顯存預留',adv_eses:'Eses 雙圖對比（原圖 vs 對比圖）',adv_axis:'軸',adv_vram:'ReservedVRAM 顯存預留',adv_output:'輸出設定',adv_out_format:'輸出格式',adv_prefix:'檔案名稱前綴模板',adv_est_hint:'估算與閾值警告顯示在主介面操作行下方',adv_lora_warn:'⚠ 預設 LoRA 已在磁碟找到；缺失將自動 _disabled + 黃提示。'},
'en-US':{nav_home:'Home',nav_generate:'Generate',nav_batch:'Batch',nav_history:'History',nav_status:'Status',nav_settings:'Settings',preset:'Preset',save_preset:'Save as preset',recent:'Recent',neg_add:'＋ Negative prompt',neg_hide:'− Hide negative prompt',btn_generate:'▶ Generate',btn_advanced:'⚙ Advanced',btn_gallery:'▦ Gallery',btn_history:'◷ History',btn_batch:'▤ Batch',btn_presets:'▣ Presets',btn_share:'Share',btn_clear:'Clear',btn_copy:'Copy',btn_free_vram:'Free VRAM',btn_restore_default:'Reset',btn_done:'Done',btn_generate_batch:'▶ Generate Batch',btn_cancel:'Cancel',batch_prompt_file:'Prompt File',batch_param_grid:'Param Grid',search_placeholder:'Search',phase_connecting:'Connecting',phase_loading_workflow:'Loading workflow',phase_engine_ready:'Engine ready',phase_patching:'Patching',phase_queuing:'Queuing',phase_sampling:'Sampling',phase_executing:'Executing',phase_image_saved:'Image saved',phase_completed:'Completed',phase_cancelling:'Cancelling',share_no_output:'No output to share yet',share_copied:'Image link & prompt copied',share_failed:'Share failed',g_all:'All',top_theme:'Theme',top_color:'Color',top_font:'Font',top_about:'About',top_settings:'Settings',top_model:'Model',top_lang:'Language',drawer_gallery:'Gallery',drawer_gallery_hint:'Top drawer · click a card to open viewer',drawer_history:'History',drawer_history_hint:'Search / seed',drawer_batch:'Batch',drawer_batch_hint:'Bottom drawer · Prompt file / Param grid',drawer_settings:'Settings',drawer_settings_hint:'Top drawer · Global config',drawer_status:'System Status',drawer_status_hint:'Top drawer · click status in footer',drawer_about:'About',drawer_about_hint:'Top drawer · App section',tagline_pre:'Turn every heartfelt word,',tagline_em:'into light',sub_tagline:'Describe your creative idea and let AI craft a one-of-a-kind image',snap_engine:'Engine',snap_res:'Resolution',snap_est:'Est.',snap_imgs:'imgs',est_line:'Estimated {total} images = 1 Prompt × {n} batch',warn_500:'⚠ Over 500 images: suggested to generate at night, ~40min (RTX 4090 estimate)',warn_5000:'⚠ Over 5000 images: auto checkpoint every 100; clicking Generate needs extra confirm',type_original:'Original',type_upscaled:'Upscaled',type_compare:'Compare',st_completed:'Completed',st_failed:'Failed',st_cancelled:'Cancelled',st_processing:'Processing',st_pending:'Queued',char_count:'{n} chars · ≈{t} tokens',th_preview:'Preview',th_prompt:'Prompt',th_status:'Status',th_actions:'Actions',hist_status_all:'Status',hist_purge:'Purge',hist_clear:'Clear',btn_prev_page:'‹ Prev',btn_next_page:'Next ›',hist_total:'{n} total',hist_page:'Page {p}/{tp}',st_interrupted:'Interrupted',drawer_adv:'Advanced',drawer_adv_hint:'22 items · live',drawer_presets:'Presets',drawer_presets_hint:'Linked to generate page',set_engine_model:'Engine & Models',set_default_engine:'Default Engine',set_workflow_dir:'Workflow Directory',set_model_mode:'Model Source Mode',set_seedvr2_dir:'SeedVR2 Model',set_scan:'Full Resource Scan',set_scan_hint:'Pending',set_runtime:'Runtime',set_heartbeat:'Heartbeat Poll',set_hb_30:'Every 30s',set_hb_60:'Every 60s',set_spawn:'Auto-Spawn Backend',set_spawn_on:'On (auto-recover)',set_spawn_off:'Off',set_lb:'Load Balancing',set_lb_local:'Local First',set_lb_rr:'Round Robin',set_lb_lc:'Least Connections',set_retention:'Retention Policy',set_hist_ret:'History Retention',set_ret_forever:'Forever',set_config:'Config',set_export_json:'Export Config JSON',set_import_json:'Import Config JSON',about_sub:'Z-Image Turbo Image Generation Platform',about_desc:'A local-first AI image generation workbench: Z-Image-Turbo native in-process inference, 6-layer LoRA stacking, SeedVR2 upscaling, Eses dual-image compare and VRAM reservation — a chat-like UI hides the workflow complexity.',about_author:'Author',about_version:'Version',about_license:'License',about_github:'GitHub Repo',feat_native:'Native Engine',feat_native_sub:'Z-Image-Turbo, in-process inference',feat_lora:'6-Layer LoRA',feat_lora_sub:'Chained ids 16→21, auto-relink when disabled',feat_seedvr2:'SeedVR2 Upscale',feat_seedvr2_sub:'ema_vae + 3B DiT, multiple short-edge presets',feat_compare:'Dual-Image Compare',feat_compare_sub:'Eses h/v/s stitching for visual comparison',feat_vram:'VRAM Reservation',feat_vram_sub:'ReservedVRAM keeps generation stable',feat_local:'Runs Locally',feat_local_sub:'Native in-process engine, data never leaves your machine',about_db_note:'© 2024-2026 ReSerendipity · Apache 2.0 open source · Repo & socials live — Star & follow welcome',batch_drop_title:'Drag & drop or click to upload Prompt files',batch_drop_sub:'Supports .txt / .csv · one Prompt per line · blank lines filtered · dedup across files',batch_no_files:'No files added',batch_per_line:'Batch per line',batch_mult_16:'multiple of 16',batch_grid_hint:'Checked values expand into combinations via Cartesian product; they are sent with base_config on submit.',batch_est_title:'Batch Estimate',batch_grid_combo:'Grid Combinations',batch_file_stat:'{n} files · {l} lines',batch_groups_val:'{n} combos',batch_est_line:'Estimated <b>{t}</b> images = {l} lines × {g} combos × batch {b}',batch_queue_title:'Task Queue',batch_line_n:'{n} lines',batch_parsed:'Parsed',batch_remove:'Remove',batch_none:'No batch tasks',batch_querying:'Querying batch {id}…',batch_title_line:'batch {id} · {n} tasks total',batch_status_line:'{c} done · {p} running · {q} queued · {f} failed · {x} cancelled',batch_not_found:'Batch not found or expired',batch_query_fail:'Query failed',batch_submit_fail:'Batch submit failed: {e}',preset_multi:'Multi-select',select_all:'Select All',cancel_select_all:'Clear Selection',sel_count:'{n} selected',preset_back:'← Back to list',preset_edit_title:'Edit Preset',preset_name:'Name',preset_desc:'Description',preset_engine:'Engine',preset_save:'Save Preset',preset_new:'＋ New Preset',presets_empty:'No presets yet — click "＋ New Preset" to create',unnamed:'Untitled',btn_apply:'Apply',btn_edit:'Edit',btn_delete:'Delete',load_failed:'Load failed',btn_got_it:'Got it',preset_del_confirm:'Delete preset "{n}"? This cannot be undone.',preset_del_fail:'Delete failed: {e}',preset_del_confirm_batch:'Delete {n} presets? This cannot be undone.',presets_deleted:'Deleted {n} presets',preset_applied:'Preset applied: {n}',preset_apply_fail:'Apply failed: {e}',preset_updated:'Preset updated',preset_saved_ok:'Preset saved',save_failed:'Save failed: {e}',param_json:'Config JSON: ',preset_default_name:'Preset {n}',hist_detail_title:'Task Detail',dd_dim:'Size · seed',dd_time:'Time · Date',dd_redraw:'Redraw with same params',dd_save_preset:'Save as preset',dd_zip:'Download ZIP',out_count:'{n} outputs',no_preview:'No preview',no_prompt:'(no prompt)',viewer_title:'Image Viewer',expand:'Expand',collapse:'Collapse',queue_idle:'Queue idle',queue_cancel:'Cancel Current',loading:'Loading…',no_images:'No images yet',gen_result:'Generated',stat_gpu:'GPU VRAM',stat_mem:'System RAM',stat_disk:'Disk outputs/',stat_resources:'Engines & Resources',stat_lora:'LoRA Resources',stat_refresh:'Refresh Status',adv_basic:'Basic Params',adv_items_8:'8 items',adv_cfg:'cfg (1.0 recommended for distilled)',adv_width:'width (multiple of 16)',adv_height:'height (multiple of 16)',adv_seed:'seed (-1 = random)',adv_lora:'LoRA Stack',adv_lora_chain:'6-layer chain',adv_strength:'Strength',adv_ready:'Connected',adv_enable_seedvr2:'Enable SeedVR2 Upscale',adv_upscale_res:'Upscale Resolution (short edge)',adv_color_corr:'Color Correction',adv_upscale_seed:'upscale_seed (independent)',adv_compare:'Compare + VRAM',adv_eses:'Eses Dual-Image Compare (original vs compare)',adv_axis:'Axis',adv_vram:'ReservedVRAM Reservation',adv_output:'Output Settings',adv_out_format:'Output Format',adv_prefix:'Filename Prefix Template',adv_est_hint:'Estimate & threshold warnings appear under the action row',adv_lora_warn:'⚠ Default LoRA found on disk; if missing it becomes _disabled with a yellow hint.'},
'ja-JP':{nav_home:'ホーム',nav_generate:'生成',nav_batch:'バッチ',nav_history:'履歴',nav_status:'ステータス',nav_settings:'設定',preset:'プリセット',save_preset:'プリセット保存',recent:'最近の生成',neg_add:'＋ ネガティブプロンプト',neg_hide:'− 閉じる',btn_generate:'▶ 生成',btn_advanced:'⚙ 詳細設定',btn_gallery:'▦ ギャラリー',btn_history:'◷ 履歴',btn_batch:'▤ バッチ',btn_presets:'▣ プリセット',btn_share:'共有',btn_clear:'クリア',btn_copy:'コピー',btn_free_vram:'VRAM解放',btn_restore_default:'デフォルトに戻す',btn_done:'完了',btn_generate_batch:'▶ バッチ生成',btn_cancel:'キャンセル',batch_prompt_file:'Promptファイル',batch_param_grid:'パラメータグリッド',search_placeholder:'検索',phase_connecting:'接続中',phase_loading_workflow:'ワークフロー読み込み中',phase_engine_ready:'エンジン準備完了',phase_patching:'パッチ適用中',phase_queuing:'キューに追加中',phase_sampling:'サンプリング中',phase_executing:'ノード実行中',phase_image_saved:'保存済み',phase_completed:'完了',phase_cancelling:'キャンセル中',share_no_output:'共有できる出力がまだありません',share_copied:'画像リンクとプロンプトをコピーしました',share_failed:'共有に失敗しました',g_all:'すべて',top_theme:'テーマ',top_color:'カラー',top_font:'フォント',top_about:'情報',top_settings:'設定',top_model:'モデル',top_lang:'言語',drawer_gallery:'ギャラリー',drawer_gallery_hint:'上部ドロワー · カードをクリックでビューアを開く',drawer_history:'履歴',drawer_history_hint:'検索 / seed',drawer_batch:'バッチ',drawer_batch_hint:'下部ドロワー · Promptファイル / パラメータグリッド',drawer_settings:'設定',drawer_settings_hint:'上部ドロワー · グローバル設定',drawer_status:'システム状態',drawer_status_hint:'上部ドロワー · 下部バー状態をクリック',drawer_about:'このアプリについて',drawer_about_hint:'上部ドロワー · アプリ内セクション',tagline_pre:'心の言葉を、',tagline_em:'光の影に変えて',sub_tagline:'アイデアを入力すれば、AIが唯一無二の画像を生成します',snap_engine:'エンジン',snap_res:'解像度',snap_est:'予定',snap_imgs:'枚',est_line:'生成予定 {total} 枚 = 1 Prompt × {n} batch',warn_500:'⚠ 500枚超：夜間生成を推奨、約40分（RTX 4090 見積）',warn_5000:'⚠ 5000枚超：自動チェックポイント（100枚毎）、「生成」を再確認',type_original:'原図',type_upscaled:'超解像',type_compare:'比較',st_completed:'完了',st_failed:'失敗',st_cancelled:'キャンセル済み',st_processing:'進行中',st_pending:'待機中',char_count:'{n} 文字 · ≈{t} token',th_preview:'プレビュー',th_prompt:'Prompt',th_status:'状態',th_actions:'操作',hist_status_all:'状態',hist_purge:'一括削除',hist_clear:'クリア',btn_prev_page:'‹ 前へ',btn_next_page:'次へ ›',hist_total:'全 {n} 件',hist_page:'{p}/{tp} ページ',st_interrupted:'中断済み',drawer_adv:'詳細設定',drawer_adv_hint:'22項目 · 即時反映',drawer_presets:'プリセット',drawer_presets_hint:'生成ページと連動',set_engine_model:'エンジンとモデル',set_default_engine:'デフォルトエンジン',set_workflow_dir:'ワークフロー目録',set_model_mode:'モデルソースモード',set_seedvr2_dir:'SeedVR2 モデル',set_scan:'全リソーススキャン',set_scan_hint:'未スキャン',set_runtime:'実行',set_heartbeat:'ハートビートポーリング',set_hb_30:'30秒ごと',set_hb_60:'60秒ごと',set_spawn:'バックエンド自動起動',set_spawn_on:'オン（自動復旧）',set_spawn_off:'オフ',set_lb:'ロードバランシング',set_lb_local:'ローカル優先',set_lb_rr:'ラウンドロビン',set_lb_lc:'最小接続',set_retention:'保持ポリシー',set_hist_ret:'履歴保持',set_ret_forever:'無期限',set_config:'設定',set_export_json:'設定JSONをエクスポート',set_import_json:'設定JSONをインポート',about_sub:'Z-Image Turbo 画像生成プラットフォーム',about_desc:'ローカルAI画像生成ワークベンチ：Z-Image-Turboネイティブエンジンのプロセス内推論、6層LoRAスタック、SeedVR2超解像、Eses二枚比較、VRAM予約。チャット風UIでワークフローの複雑さを隠蔽します。',about_author:'作者',about_version:'現在のバージョン',about_license:'ライセンス',about_github:'GitHub リポジトリ',feat_native:'ネイティブエンジン',feat_native_sub:'Z-Image-Turbo、プロセス内推論',feat_lora:'6層 LoRA',feat_lora_sub:'直列 id=16→21、無効時リンク自動再接続',feat_seedvr2:'SeedVR2 超解像',feat_seedvr2_sub:'ema_vae + 3B DiT、複数の短辺プリセット',feat_compare:'二枚比較',feat_compare_sub:'Eses h/v/s 結合で視覚比較',feat_vram:'VRAM 予約',feat_vram_sub:'ReservedVRAM で安定した生成',feat_local:'ローカル実行',feat_local_sub:'プロセス内ネイティブエンジン、データはマシンの外へ出ません',about_db_note:'© 2024-2026 ReSerendipity · Apache 2.0 オープンソース · リポジトリとSNS公開中。Star とフォロー歓迎',batch_drop_title:'ドラッグ＆ドロップまたはクリックでPromptファイルをアップロード',batch_drop_sub:'.txt / .csv 対応 · 1行に1プロンプト · 空行は自動除外 · ファイル間の重複排除',batch_no_files:'ファイル未追加',batch_per_line:'1行あたりのバッチ',batch_mult_16:'16の倍数',batch_grid_hint:'チェックした値はデカルト積で組合せに展開され、送信時に base_config と一緒に送信されます。',batch_est_title:'バッチ見積もり',batch_grid_combo:'グリッド組合せ',batch_file_stat:'{n}個ファイル · {l}行',batch_groups_val:'{n} 組',batch_est_line:'生成予定 <b>{t}</b> 枚 = {l}行 × {g}組 × batch {b}',batch_queue_title:'タスクキュー',batch_line_n:'{n}行',batch_parsed:'解析済み',batch_remove:'削除',batch_none:'バッチタスクはありません',batch_querying:'バッチ {id} を照会中…',batch_title_line:'batch {id} · 合計 {n} タスク',batch_status_line:'{c} 完了 · {p} 進行中 · {q} 待機 · {f} 失敗 · {x} キャンセル',batch_not_found:'バッチが見つからないか期限切れ',batch_query_fail:'照会失敗',batch_submit_fail:'バッチ送信失敗: {e}',preset_multi:'複数選択',select_all:'すべて選択',cancel_select_all:'選択解除',sel_count:'{n}件選択中',preset_back:'← 一覧に戻る',preset_edit_title:'プリセット編集',preset_name:'名前',preset_desc:'説明',preset_engine:'エンジン',preset_save:'プリセット保存',preset_new:'＋ 新規プリセット',presets_empty:'プリセットなし — 「＋ 新規プリセット」で作成',unnamed:'無題',btn_apply:'適用',btn_edit:'編集',btn_delete:'削除',load_failed:'読み込み失敗',btn_got_it:'了解',preset_del_confirm:'プリセット「{n}」を削除しますか？元に戻せません。',preset_del_fail:'削除失敗: {e}',preset_del_confirm_batch:'{n} 個のプリセットを削除しますか？元に戻せません。',presets_deleted:'{n} 個のプリセットを削除しました',preset_applied:'プリセット適用: {n}',preset_apply_fail:'適用失敗: {e}',preset_updated:'プリセットを更新しました',preset_saved_ok:'プリセットを保存しました',save_failed:'保存失敗: {e}',param_json:'設定 JSON: ',preset_default_name:'プリセット {n}',hist_detail_title:'タスク詳細',dd_dim:'サイズ · seed',dd_time:'時間 · 日時',dd_redraw:'同じパラメータで再生成',dd_save_preset:'プリセットとして保存',dd_zip:'ZIPをダウンロード',out_count:'{n} 枚出力',no_preview:'プレビューなし',no_prompt:'(プロンプトなし)',viewer_title:'画像ビューア',expand:'展開',collapse:'折りたたむ',queue_idle:'キューは空です',queue_cancel:'現在をキャンセル',loading:'読み込み中…',no_images:'画像はまだありません',gen_result:'生成結果',stat_gpu:'GPU メモリ',stat_mem:'システムメモリ',stat_disk:'ディスク outputs/',stat_resources:'エンジンとリソース',stat_lora:'LoRA リソース',stat_refresh:'状態を更新',adv_basic:'基本パラメータ',adv_items_8:'8項目',adv_cfg:'cfg（蒸留推奨 1.0）',adv_width:'width（16の倍数）',adv_height:'height（16の倍数）',adv_seed:'seed（-1 = ランダム）',adv_lora:'LoRA スタック',adv_lora_chain:'6層直列',adv_strength:'強度',adv_ready:'接続済み',adv_enable_seedvr2:'SeedVR2 超解像を有効化',adv_upscale_res:'超解像解像度（短辺）',adv_color_corr:'色補正',adv_upscale_seed:'upscale_seed（独立）',adv_compare:'比較 + VRAM予約',adv_eses:'Eses 二枚比較（原図 vs 比較図）',adv_axis:'軸',adv_vram:'ReservedVRAM 予約',adv_output:'出力設定',adv_out_format:'出力形式',adv_prefix:'ファイル名プレフィックス',adv_est_hint:'見積もりと閾値警告は操作行の下に表示されます',adv_lora_warn:'⚠ デフォルトLoRAはディスクにあります。無い場合は _disabled 化し黄色で提示します。'},
'ko-KR':{nav_home:'홈',nav_generate:'생성',nav_batch:'배치',nav_history:'기록',nav_status:'상태',nav_settings:'설정',preset:'프리셋',save_preset:'현재를 프리셋으로 저장',recent:'최근 생성',neg_add:'＋ 네거티브 프롬프트',neg_hide:'− 접기',btn_generate:'▶ 생성',btn_advanced:'⚙ 고급 매개변수',btn_gallery:'▦ 갤러리',btn_history:'◷ 기록',btn_batch:'▤ 배치',btn_presets:'▣ 프리셋',btn_share:'공유',btn_clear:'지우기',btn_copy:'복사',btn_free_vram:'VRAM 해제',btn_restore_default:'기본값 복원',btn_done:'완료',btn_generate_batch:'▶ 배치 생성',btn_cancel:'취소',batch_prompt_file:'Prompt 파일',batch_param_grid:'매개변수 그리드',search_placeholder:'검색',phase_connecting:'연결 중',phase_loading_workflow:'워크플로 로드 중',phase_engine_ready:'엔진 준비 완료',phase_patching:'패치 적용 중',phase_queuing:'대기열 추가 중',phase_sampling:'샘플링 중',phase_executing:'노드 실행 중',phase_image_saved:'저장됨',phase_completed:'완료',phase_cancelling:'취소 중',share_no_output:'공유할 출력이 아직 없습니다',share_copied:'이미지 링크와 프롬프트를 복사했습니다',share_failed:'공유 실패',g_all:'전체',top_theme:'테마',top_color:'색상',top_font:'글꼴',top_about:'정보',top_settings:'설정',top_model:'모델',top_lang:'언어',drawer_gallery:'갤러리',drawer_gallery_hint:'상단 서랍 · 카드 클릭 시 뷰어 열림',drawer_history:'기록',drawer_history_hint:'검색 / seed',drawer_batch:'배치',drawer_batch_hint:'하단 서랍 · Prompt 파일 / 매개변수 그리드',drawer_settings:'설정',drawer_settings_hint:'상단 서랍 · 전역 설정',drawer_status:'시스템 상태',drawer_status_hint:'상단 서랍 · 하단바 상태 클릭',drawer_about:'프로젝트 소개',drawer_about_hint:'상단 서랍 · 앱 내 섹션',tagline_pre:'마음의 말을,',tagline_em:'빛과 그림자로',sub_tagline:'창의적인 설명을 입력하면 AI가 독특한 이미지를 생성합니다',snap_engine:'엔진',snap_res:'해상도',snap_est:'예상',snap_imgs:'장',est_line:'예상 생성 {total}장 = 1 Prompt × {n} batch',warn_500:'⚠ 500장 초과: 야간 생성을 권장, 약 40분(RTX 4090 추정)',warn_5000:'⚠ 5000장 초과: 자동 체크포인트(100장마다), 「생성」클릭 시 재확인 필요',type_original:'원본',type_upscaled:'초해상도',type_compare:'비교',st_completed:'완료',st_failed:'실패',st_cancelled:'취소됨',st_processing:'진행 중',st_pending:'대기 중',char_count:'{n}자 · ≈{t} token',th_preview:'미리보기',th_prompt:'Prompt',th_status:'상태',th_actions:'작업',hist_status_all:'상태',hist_purge:'일괄 삭제',hist_clear:'지우기',btn_prev_page:'‹ 이전',btn_next_page:'다음 ›',hist_total:'총 {n}건',hist_page:'{p}/{tp} 페이지',st_interrupted:'중단됨',drawer_adv:'고급 매개변수',drawer_adv_hint:'22개 항목 · 즉시 반영',drawer_presets:'프리셋',drawer_presets_hint:'생성 페이지와 연동',set_engine_model:'엔진 및 모델',set_default_engine:'기본 엔진',set_workflow_dir:'워크플로 디렉터리',set_model_mode:'모델 소스 모드',set_seedvr2_dir:'SeedVR2 모델',set_scan:'전체 리소스 스캔',set_scan_hint:'대기 중',set_runtime:'실행',set_heartbeat:'하트비트 폴링',set_hb_30:'30초마다',set_hb_60:'60초마다',set_spawn:'백엔드 자동 실행',set_spawn_on:'켜짐(자동 복구)',set_spawn_off:'끄기',set_lb:'로드 밸런싱',set_lb_local:'로컬 우선',set_lb_rr:'라운드 로빈',set_lb_lc:'최소 연결',set_retention:'보존 정책',set_hist_ret:'기록 보존',set_ret_forever:'영구',set_config:'구성',set_export_json:'설정 JSON 내보내기',set_import_json:'설정 JSON 가져오기',about_sub:'Z-Image Turbo 이미지 생성 플랫폼',about_desc:'로컬 AI 이미지 생성 워크벤치: Z-Image-Turbo 네이티브 엔진 프로세스 내 추론, 6단 LoRA 스택, SeedVR2 초해상도, Eses 이중 비교, VRAM 예약. 대화형 UI로 워크플로 복잡성을 숨깁니다.',about_author:'저자',about_version:'현재 버전',about_license:'라이선스',about_github:'GitHub 저장소',feat_native:'네이티브 엔진',feat_native_sub:'Z-Image-Turbo, 프로세스 내 추론',feat_lora:'6단 LoRA',feat_lora_sub:'직렬 id=16→21, 비활성 시 자동 재연결',feat_seedvr2:'SeedVR2 업스케일',feat_seedvr2_sub:'ema_vae + 3B DiT, 다양한 단변 프리셋',feat_compare:'이중 이미지 비교',feat_compare_sub:'Eses h/v/s 결합으로 직관적 비교',feat_vram:'VRAM 예약',feat_vram_sub:'ReservedVRAM으로 안정적 생성',feat_local:'로컬 실행',feat_local_sub:'프로세스 내 네이티브 엔진, 데이터가 기기를 벗어나지 않음',about_db_note:'© 2024-2026 ReSerendipity · Apache 2.0 오픈소스 · 저장소와 SNS 오픈 — Star와 팔로우 환영',batch_drop_title:'드래그 앤 드롭 또는 클릭하여 Prompt 파일 업로드',batch_drop_sub:'.txt / .csv 지원 · 줄당 Prompt 1개 · 빈 줄 자동 제외 · 파일 간 중복 제거',batch_no_files:'파일 없음',batch_per_line:'줄당 배치',batch_mult_16:'16의 배수',batch_grid_hint:'체크한 값은 데카르트 곱으로 조합되어 제출 시 base_config와 함께 전송됩니다.',batch_est_title:'배치 예상',batch_grid_combo:'그리드 조합',batch_file_stat:'{n}개 파일 · {l}행',batch_groups_val:'{n} 조합',batch_est_line:'예상 생성 <b>{t}</b>장 = {l}행 × {g}조합 × batch {b}',batch_queue_title:'작업 큐',batch_line_n:'{n}행',batch_parsed:'파싱됨',batch_remove:'제거',batch_none:'배치 작업 없음',batch_querying:'배치 {id} 조회 중…',batch_title_line:'batch {id} · 총 {n}개 작업',batch_status_line:'{c} 완료 · {p} 진행 중 · {q} 대기 · {f} 실패 · {x} 취소',batch_not_found:'배치를 찾을 수 없거나 만료됨',batch_query_fail:'조회 실패',batch_submit_fail:'배치 제출 실패: {e}',preset_multi:'다중 선택',select_all:'전체 선택',cancel_select_all:'선택 해제',sel_count:'{n}개 선택됨',preset_back:'← 목록으로',preset_edit_title:'프리셋 편집',preset_name:'이름',preset_desc:'설명',preset_engine:'엔진',preset_save:'프리셋 저장',preset_new:'＋ 새 프리셋',presets_empty:'프리셋 없음 — 「＋ 새 프리셋」으로 생성',unnamed:'이름 없음',btn_apply:'적용',btn_edit:'편집',btn_delete:'삭제',load_failed:'로드 실패',btn_got_it:'알겠음',preset_del_confirm:'프리셋 「{n}」을 삭제할까요? 되돌릴 수 없습니다.',preset_del_fail:'삭제 실패: {e}',preset_del_confirm_batch:'{n}개 프리셋을 삭제할까요? 되돌릴 수 없습니다.',presets_deleted:'{n}개 프리셋 삭제됨',preset_applied:'프리셋 적용됨: {n}',preset_apply_fail:'적용 실패: {e}',preset_updated:'프리셋 업데이트됨',preset_saved_ok:'프리셋 저장됨',save_failed:'저장 실패: {e}',param_json:'설정 JSON: ',preset_default_name:'프리셋 {n}',hist_detail_title:'작업 상세',dd_dim:'크기 · seed',dd_time:'소요 · 시간',dd_redraw:'동일 매개변수로 다시 생성',dd_save_preset:'프리셋으로 저장',dd_zip:'ZIP 다운로드',out_count:'{n}장 출력',no_preview:'미리보기 없음',no_prompt:'(프롬프트 없음)',viewer_title:'이미지 뷰어',expand:'펼치기',collapse:'접기',queue_idle:'큐 비어 있음',queue_cancel:'현재 작업 취소',loading:'로딩 중…',no_images:'이미지 없음',gen_result:'생성 결과',stat_gpu:'GPU VRAM',stat_mem:'시스템 메모리',stat_disk:'디스크 outputs/',stat_resources:'엔진 및 리소스',stat_lora:'LoRA 리소스',stat_refresh:'상태 새로고침',adv_basic:'기본 매개변수',adv_items_8:'8개 항목',adv_cfg:'cfg(증류 권장 1.0)',adv_width:'width(16의 배수)',adv_height:'height(16의 배수)',adv_seed:'seed(-1 = 무작위)',adv_lora:'LoRA 스택',adv_lora_chain:'6단 직렬',adv_strength:'강도',adv_ready:'연결됨',adv_enable_seedvr2:'SeedVR2 업스케일 활성화',adv_upscale_res:'업스케일 해상도(짧은 변)',adv_color_corr:'색상 보정',adv_upscale_seed:'upscale_seed(독립)',adv_compare:'비교 + VRAM 예약',adv_eses:'Eses 이중 이미지 비교(원본 vs 비교)',adv_axis:'축',adv_vram:'ReservedVRAM 예약',adv_output:'출력 설정',adv_out_format:'출력 형식',adv_prefix:'파일명 접두사 템플릿',adv_est_hint:'예상 및 임계값 경고가 작업 행 아래에 표시됩니다',adv_lora_warn:'⚠ 기본 LoRA가 디스크에 있습니다. 없으면 _disabled 처리 및 노란색 안내.'}
};
var langSel=document.getElementById('langSelect');
function applyLang(l){document.documentElement.setAttribute('data-lang',l);var d=I18N[l]||I18N['zh-CN'];document.querySelectorAll('[data-i18n]').forEach(function(el){var k=el.getAttribute('data-i18n');if(d[k])el.textContent=d[k];});document.querySelectorAll('[data-i18n-ph]').forEach(function(el){var k=el.getAttribute('data-i18n-ph');if(d[k])el.placeholder=d[k];});document.querySelectorAll('[data-i18n-title]').forEach(function(el){var k=el.getAttribute('data-i18n-title');if(d[k])el.title=d[k];});/* 动态元素：negToggle 根据开关状态设置 */var nt=document.getElementById('negToggle');if(nt){var open=nt.classList.contains('open');nt.textContent=open?(d.neg_hide||'− '):(d.neg_add||'＋ ');}}
function trPhase(phase){var l=document.documentElement.getAttribute('data-lang')||'zh-CN';var d=I18N[l]||I18N['zh-CN'];return d[phase]||phase;}
function escHtml(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
langSel.addEventListener('change',function(e){applyLang(e.target.value);});
/* 顶栏图标菜单：引擎 / 语言 */
var engMenu=document.getElementById('engMenu'),langMenu=document.getElementById('langMenu');
function closeMenus(){engMenu.classList.remove('show');langMenu.classList.remove('show');}
document.getElementById('engIcon').addEventListener('click',function(e){e.stopPropagation();langMenu.classList.remove('show');engMenu.classList.toggle('show');});
document.getElementById('langIcon').addEventListener('click',function(e){e.stopPropagation();engMenu.classList.remove('show');langMenu.classList.toggle('show');});
document.querySelectorAll('#engMenu .ip-item').forEach(function(b){b.addEventListener('click',function(){document.querySelectorAll('#engMenu .ip-item').forEach(function(x){x.classList.remove('on');});b.classList.add('on');document.getElementById('engineSelect').value=b.dataset.v;document.getElementById('engineSelect').dispatchEvent(new Event('change'));closeMenus();});});
document.querySelectorAll('#langMenu .ip-item').forEach(function(b){b.addEventListener('click',function(){document.querySelectorAll('#langMenu .ip-item').forEach(function(x){x.classList.remove('on');});b.classList.add('on');langSel.value=b.dataset.l;localStorage.setItem('imm_lang',b.dataset.l);applyLang(b.dataset.l);closeMenus();});});
document.addEventListener('click',function(e){if(!e.target.closest('.ico-wrap'))closeMenus();});
/* ---------- 分享 ---------- */
var shareBtn=document.querySelector('.share-btn');
function shareCurrent(){
  function _t(k){var d=I18N[langSel.value]||I18N['zh-CN'];return d[k]||k;}
  var img=document.querySelector('#outGrid .r-card img');
  var src=img?img.getAttribute('src'):'';
  if(!src){appConfirm(_t('share_no_output'),{okText:tr('btn_got_it')}).then(function(){});return;}
  var url=location.origin+src;
  var text=(posPrompt&&posPrompt.value)?posPrompt.value:'Image-MultiModel';
  function copyFallback(){
    if(!navigator.clipboard){appConfirm(_t('share_failed'),{okText:tr('btn_got_it')}).then(function(){});return;}
    navigator.clipboard.writeText(text+'\n'+url).then(function(){appConfirm(_t('share_copied'),{okText:tr('btn_got_it')}).then(function(){});}).catch(function(){appConfirm(_t('share_failed'),{okText:tr('btn_got_it')}).then(function(){});});
  }
  if(navigator.share){
    fetch(url).then(function(r){return r.blob();}).then(function(blob){
      var payload={title:'Image-MultiModel',text:text,url:url};
      var file=new File([blob],'image.png',{type:blob.type||'image/png'});
      payload.files=[file];
      if(navigator.canShare&&navigator.canShare(payload)){return navigator.share(payload);}
      delete payload.files;
      return navigator.share(payload);
    }).catch(function(err){
      if(err&&err.name==='AbortError')return;copyFallback();
    });
  }else{
    copyFallback();
  }
}
if(shareBtn)shareBtn.addEventListener('click',shareCurrent);
/* ---------- 主题 ---------- */
var themeBtn=document.getElementById('themeToggle');
/* 主题切换持久化逻辑在 F10 节统一处理，此处不再绑定 */
/* ---------- 抽屉总控 ---------- */
var drawer=document.getElementById('drawer'),scrim=document.getElementById('scrim');
var mTitle=document.getElementById('mTitle'),mHint=document.getElementById('mHint'),drawerFoot=document.getElementById('drawerFoot');
var MODULES={adv:['drawer_adv','drawer_adv_hint','sec-adv',false],presets:['drawer_presets','drawer_presets_hint','sec-presets',true]};
function closeHist(){document.getElementById('histDrawer').classList.remove('open');}
function closeGalleryD(){document.getElementById('galleryDrawer').classList.remove('open');}
function openRight(key){
  closeBottom();closeTop();closeHist();closeGalleryD();
  var m=MODULES[key];
  mTitle.textContent=tr(m[0]);mHint.textContent=tr(m[1]);
  document.querySelectorAll('.drawer-sec').forEach(function(s){s.classList.remove('active');});
  document.getElementById(m[2]).classList.add('active');
  drawer.classList.toggle('wide',m[3]);
  drawerFoot.classList.toggle('hide',key!=='adv');
  if(key==='adv')loadLoras();
  drawer.classList.add('open');scrim.classList.add('show');
}
function closeRight(){drawer.classList.remove('open');scrim.classList.remove('show');}
document.getElementById('drawerToggle').addEventListener('click',function(){openRight('adv');});
document.getElementById('drawerClose').addEventListener('click',closeRight);
document.getElementById('drawerDone').addEventListener('click',closeRight);
scrim.addEventListener('click',function(){closeRight();closeBottom();});
function openHistD(){closeRight();closeBottom();closeTop();closeGalleryD();document.getElementById('histDrawer').classList.add('open');showHistList();}
function openGalleryD(){closeRight();closeBottom();closeTop();closeHist();document.getElementById('galleryDrawer').classList.add('open');renderGallery();}
document.getElementById('openGallery').addEventListener('click',openGalleryD);
document.getElementById('openHistory').addEventListener('click',openHistD);
document.getElementById('openPresets').addEventListener('click',function(){openRight('presets');showPList();});
document.getElementById('openBatch').addEventListener('click',function(){closeRight();closeTop();closeHist();closeGalleryD();document.getElementById('batchDrawer').classList.add('open');renderBatchQueue();});
document.getElementById('histClose').addEventListener('click',closeHist);
document.getElementById('galleryClose').addEventListener('click',closeGalleryD);
/* ---------- 底部/顶部抽屉 ---------- */
function closeBottom(){['setDrawer','aboutDrawer','batchDrawer'].forEach(function(id){document.getElementById(id).classList.remove('open');});['setScrim'].forEach(function(id){document.getElementById(id).classList.remove('show');});}
function closeTop(){document.getElementById('statDrawer').classList.remove('open');}
var setD=document.getElementById('setDrawer'),setSc=document.getElementById('setScrim');
function openSet(){closeRight();closeBottom();closeTop();closeHist();closeGalleryD();setD.classList.add('open');setSc.classList.add('show');}
document.getElementById('setOpen').addEventListener('click',function(){openSet();});
document.getElementById('setClose').addEventListener('click',function(){setD.classList.remove('open');setSc.classList.remove('show');});
setSc.addEventListener('click',function(){setD.classList.remove('open');setSc.classList.remove('show');});
var aboutDrawer=document.getElementById('aboutDrawer');
function openAbout(){closeRight();closeBottom();closeTop();closeHist();closeGalleryD();aboutDrawer.classList.add('open');}
document.getElementById('aboutBtn').addEventListener('click',openAbout);
document.getElementById('aboutClose').addEventListener('click',function(){aboutDrawer.classList.remove('open');});
document.getElementById('batchClose').addEventListener('click',function(){document.getElementById('batchDrawer').classList.remove('open');});
var statD=document.getElementById('statDrawer');
function openStat(){closeRight();closeBottom();closeHist();closeGalleryD();statD.classList.add('open');}
document.querySelectorAll('.sb-click').forEach(function(el){el.addEventListener('click',function(){openStat();});});
document.getElementById('statClose').addEventListener('click',closeTop);
/* ---------- Esc ---------- */
document.addEventListener('keydown',function(e){if(e.key==='Escape'){closeRight();closeBottom();closeTop();closeHist();closeGalleryD();viewer.classList.remove('show');qpop.classList.remove('show');}});
/* ---------- 负向提示词 / 示例 / Prompt ---------- */
var negBox=document.getElementById('negBox'),negToggle=document.getElementById('negToggle');
negToggle.addEventListener('click',function(){var open=negBox.classList.toggle('open');var d=I18N[langSel.value]||I18N['zh-CN'];negToggle.textContent=open?d.neg_hide:d.neg_add;});
var posPrompt=document.getElementById('posPrompt'),negPrompt=document.getElementById('negPrompt');
function updatePosMeta(){var n=posPrompt.value.length;document.getElementById('posMeta').textContent=tr('char_count',{n:n,t:Math.max(1,Math.round(n/0.7))});}
function updateNegMeta(){document.getElementById('negMeta').textContent=tr('char_count',{n:negPrompt.value.length,t:Math.max(1,Math.round(negPrompt.value.length/0.7))});}
posPrompt.addEventListener('input',updatePosMeta);negPrompt.addEventListener('input',updateNegMeta);
document.getElementById('clearPos').addEventListener('click',function(){posPrompt.value='';updatePosMeta();});
document.getElementById('copyPos').addEventListener('click',function(){posPrompt.select();document.execCommand('copy');});
document.getElementById('clearNeg').addEventListener('click',function(){negPrompt.value='';updateNegMeta();});
document.getElementById('copyNeg').addEventListener('click',function(){negPrompt.select();document.execCommand('copy');});
document.querySelectorAll('.p-chip').forEach(function(c){c.addEventListener('click',function(){document.querySelectorAll('.p-chip').forEach(function(x){x.classList.remove('on');});c.classList.add('on');});});
/* ---------- 手风琴 / stepper / 滑块 / LoRA / dice / batch ---------- */
document.querySelectorAll('.acc-head').forEach(function(h){h.addEventListener('click',function(){h.parentElement.classList.toggle('open');});});
document.querySelectorAll('.stepper').forEach(function(s){var inp=s.querySelector('input'),step=+(s.dataset.step||1),min=+(s.dataset.min||-Infinity),max=+(s.dataset.max||Infinity);s.querySelector('.st-dec').addEventListener('click',function(){inp.value=Math.max(min,(+inp.value||0)-step);inp.dispatchEvent(new Event('input'));});s.querySelector('.st-inc').addEventListener('click',function(){inp.value=Math.min(max,(+inp.value||0)+step);inp.dispatchEvent(new Event('input'));});});
document.querySelectorAll('.quick-sz').forEach(function(q){q.querySelectorAll('button').forEach(function(b){b.addEventListener('click',function(){q.querySelectorAll('button').forEach(function(x){x.classList.remove('on');});b.classList.add('on');var tg=q.closest('.fgroup').querySelector('.stepper input');tg.value=b.textContent;tg.dispatchEvent(new Event('input'));});});});
document.querySelectorAll('#loraStack .r2 input[type=range], .range-row input[type=range]').forEach(function(r){var v=r.nextElementSibling;function upd(){v.textContent=(+r.value).toFixed(2);v.style.color=Math.abs(+r.value)>1.5?'var(--red)':'var(--accent)';}r.addEventListener('input',upd);upd();});
document.querySelectorAll('.lora-name').forEach(function(sel){sel.addEventListener('change',function(){var row=sel.closest('.lora-row');row.classList.toggle('disabled',sel.value==='— 禁用 —');});});
document.querySelectorAll('.dice').forEach(function(b){b.addEventListener('click',function(){var inp=document.getElementById(b.dataset.target);inp.value=Math.floor(Math.random()*9007199254740991);inp.dispatchEvent(new Event('input'));if(b.dataset.target==='seed'){document.getElementById('seedHint').textContent='实际 seed：'+inp.value;document.getElementById('seedHint').style.color='var(--accent)';}});});
document.getElementById('reuseSeed').addEventListener('click',function(){API.get('/tasks?page=1&page_size=1').then(function(r){var t=r.tasks&&r.tasks[0];var s=t&&t.generation_config?t.generation_config.seed:null;if(s===undefined||s===null||s===-1){s=Math.floor(Math.random()*9007199254740991);}var e=document.getElementById('seed');e.value=s;e.dispatchEvent(new Event('input'));document.getElementById('seedHint').textContent='实际 seed：'+s;document.getElementById('seedHint').style.color='var(--accent)';}).catch(function(){var s=Math.floor(Math.random()*9007199254740991);var e=document.getElementById('seed');e.value=s;e.dispatchEvent(new Event('input'));document.getElementById('seedHint').textContent='实际 seed：'+s;});});
document.getElementById('b10').addEventListener('click',function(){var e=document.getElementById('batchSize');e.value=Math.min(9999,(+e.value||0)+10);e.dispatchEvent(new Event('input'));});
document.getElementById('b100').addEventListener('click',function(){var e=document.getElementById('batchSize');e.value=Math.min(9999,(+e.value||0)+100);e.dispatchEvent(new Event('input'));});
document.getElementById('restoreBtn').addEventListener('click',function(){
  appConfirm('将恢复为后端默认参数，当前已修改的高级参数会被覆盖。确认？',{okText:'恢复默认',danger:true}).then(function(ok){if(ok)resetToDefaults();});
});
/* ---------- 估算 + 快照 ---------- */
function estCount(){var n=+document.getElementById('batchSize').value||1;return {n:n,coef:1,total:n};}
function tr(k,params){var l=document.documentElement.getAttribute('data-lang')||'zh-CN';var d=I18N[l]||I18N['zh-CN'];var s=d[k];if(s===undefined||s===null){s=k.indexOf('st_')===0?k.substring(3):k;}if(params){for(var key in params){s=s.split('{'+key+'}').join(params[key]);}}return s;}
function syncChips(){document.getElementById('snapRes').textContent=document.getElementById('width').value+' × '+document.getElementById('height').value;document.getElementById('snapSteps').textContent=document.getElementById('steps').value;document.getElementById('snapCfg').textContent=document.getElementById('cfg').value;document.getElementById('snapOut').textContent=estCount().total;var es=document.getElementById('engineSelect');document.getElementById('snapEngine').textContent=(window.ENGINES&&ENGINES[es.value])||(es.selectedOptions&&es.selectedOptions[0]&&es.selectedOptions[0].textContent)||'—';}
function updateEst(){var e=estCount(),line=document.getElementById('estLine');document.getElementById('bsWarn').style.display=e.n>500?'':'none';document.getElementById('bsWarn').style.color=e.n>5000?'var(--red)':'var(--amber)';line.innerHTML=tr('est_line',{total:e.total,n:e.n});line.className='est-line'+(e.total>=5000?' red':(e.total>=500?' yellow':''));document.getElementById('warn500').classList.toggle('show',e.total>=500&&e.total<5000);document.getElementById('warn5000').classList.toggle('show',e.total>=5000);syncChips();}
['batchSize','seedvr2Toggle','esesToggle','width','height','steps','cfg'].forEach(function(id){var el=document.getElementById(id);el.addEventListener('input',updateEst);el.addEventListener('change',updateEst);});
document.getElementById('engineSelect').addEventListener('change',function(){syncEngMenu();if(_CFG&&_CFG.models&&_CFG.models.engines){var ec=_CFG.models.engines[this.value];if(ec){var w=document.getElementById('width'),h=document.getElementById('height');if(!w.dataset.touched)w.value=ec.default_width||w.value;if(!h.dataset.touched)h.value=ec.default_height||h.value;}}syncChips();updateEst();});
updateEst();
/* ---------- 生成模拟 ---------- */
/* P2-10：应用内确认弹层（替代浏览器原生 confirm） */
function appConfirm(msg,opts){
  opts=opts||{};
  return new Promise(function(res){
    var box=document.getElementById('appConfirm');
    if(!box){res(window.confirm(msg));return;}
    var msgEl=document.getElementById('acMsg');if(msgEl)msgEl.textContent=msg;
    var title=document.getElementById('acTitle');if(title)title.textContent=opts.title||'确认';
    var ok=document.getElementById('acOk');if(ok){ok.textContent=opts.okText||'确定';ok.classList.toggle('text-danger',!!opts.danger);}
    var cancel=document.getElementById('acCancel');
    box.style.display='flex';
    function done(v){box.style.display='none';if(ok)ok.onclick=null;if(cancel)cancel.onclick=null;res(v);}
    if(ok)ok.onclick=function(){done(true);};
    if(cancel)cancel.onclick=function(){done(false);};
  });
}
var genBtn=document.getElementById('genBtn');
var progFill=document.getElementById('progFill'),phaseText=document.getElementById('phaseText'),genProgress=document.getElementById('genProgress');
var outGrid=document.getElementById('outGrid');
var qpDot=document.getElementById('qpDot'),qpText=document.getElementById('qpText'),qpPct=document.getElementById('qpPct'),qpop=document.getElementById('queuePop');
var timer=null,progress=0;
/* 生成流程由下方 F1 真实层接管（startGenReal / cancelGenReal / renderOutReal） */
document.getElementById('queuePill').addEventListener('click',function(){qpop.classList.toggle('show');if(qpop.classList.contains('show'))renderQueue();});
document.getElementById('qpClose').addEventListener('click',function(e){e.stopPropagation();qpop.classList.remove('show');});
/* (队列取消已由 F1 真实层接管) */
/* ---------- 图片展示（抽屉内 + 悬浮查看器） ---------- */
/* 图库数据由 F7 从 /api/outputs 真实加载，不再使用原型示例 */
var gMasonry=document.getElementById('gMasonry');
function renderGallery(filter){filter=filter||'all';gMasonry.innerHTML='<p class="ph-note pad-lg">'+tr('loading')+'</p>';}
document.querySelectorAll('#galleryDrawer .f-chip').forEach(function(b){b.addEventListener('click',function(){document.querySelectorAll('#galleryDrawer .f-chip').forEach(function(x){x.classList.remove('on');});b.classList.add('on');renderGallery(b.dataset.f);});});
var viewer=document.getElementById('viewer'),vImg=document.getElementById('vImg'),vTitle=document.getElementById('vTitle'),vSeed=document.getElementById('vSeed'),vMeta=document.getElementById('vMeta'),vZoomVal=document.getElementById('vZoomVal');
var zoom=100,compare=false,cur=0,_curViewer=null,_navList=null,_navIdx=-1;
function openViewer(i){/* 由 F7 openViewerReal 接管 */}
function renderImg(){/* 由 F7 覆盖为真实图片渲染 */}
document.getElementById('vCompare').addEventListener('click',function(){compare=!compare;renderImg();});
document.getElementById('vZoomIn').addEventListener('click',function(){zoom=Math.min(200,zoom+25);renderImg();});
document.getElementById('vZoomOut').addEventListener('click',function(){zoom=Math.max(50,zoom-25);renderImg();});
document.getElementById('vZoomReset').addEventListener('click',function(){zoom=100;renderImg();});
document.getElementById('vFav').addEventListener('click',function(){this.classList.toggle('on');this.textContent=this.classList.contains('on')?'★':'☆';});
document.getElementById('vClose').addEventListener('click',function(){viewer.classList.remove('show');});
document.getElementById('vDownload').addEventListener('click',function(){if(_curViewer)window.open('/api/outputs/'+_curViewer.path,'_blank');});
document.getElementById('vRedraw').addEventListener('click',function(){if(_curViewer&&_curViewer.task_id){var tid=_curViewer.task_id;viewer.classList.remove('show');redrawTask(tid);}});
document.getElementById('vPrev').addEventListener('click',function(){navViewer(-1);});
document.getElementById('vNext').addEventListener('click',function(){navViewer(1);});
document.getElementById('vFull').addEventListener('click',function(){if(document.fullscreenElement){document.exitFullscreen().catch(function(){});}else if(viewer.requestFullscreen){viewer.requestFullscreen().catch(function(){});}});
document.getElementById('vPromptToggle').addEventListener('click',function(){var info=document.getElementById('vInfo');var expanded=info.classList.toggle('expanded');this.textContent=expanded?tr('collapse'):tr('expand');});
/* 查看器打开时 ←/→ 切换上一张/下一张 */
document.addEventListener('keydown',function(e){
  if(!viewer.classList.contains('show'))return;
  if(e.key==='ArrowLeft')navViewer(-1);
  else if(e.key==='ArrowRight')navViewer(1);
});
/* ---------- 历史（抽屉内） ---------- */
var histList=document.getElementById('histList'),histDetail=document.getElementById('histDetail');
function showHistList(){histList.classList.remove('hide');histDetail.classList.remove('show');updateHistPurgeState();}
function showHistDetail(){histList.classList.add('hide');histDetail.classList.add('show');}
document.getElementById('histBack').addEventListener('click',showHistList);
/* ---------- 预设（抽屉内） ---------- */
var pList=document.getElementById('pList'),pEdit=document.getElementById('pEdit');
function showPList(){pList.style.display='';pEdit.classList.remove('show');}
function showPEdit(){pList.style.display='none';pEdit.classList.add('show');}
document.getElementById('pBack').addEventListener('click',showPList);
document.getElementById('pCancel').addEventListener('click',showPList);
document.getElementById('pNew').addEventListener('click',function(){_editPresetId=null;document.getElementById('pName').value='';document.getElementById('pDesc').value='';showPEdit();});
document.querySelectorAll('#pList .fav').forEach(function(b){b.addEventListener('click',function(){this.classList.toggle('on');this.textContent=this.classList.contains('on')?'★':'☆';});});
/* pSave 真实逻辑由 F5 节接管 */
/* ---------- 批量（底抽屉内） ---------- */
/* ---------- 批量底抽屉：真实文件上传 + 动态估算 ---------- */
var B_FILES=[];
function fmtSize(b){return b<1024?b+' B':(b/1024).toFixed(1)+' KB';}
function readBatchFiles(fileList){
  var files=Array.prototype.slice.call(fileList||[]);
  if(!files.length)return;
  var pending=files.length;
  files.forEach(function(file){
    var reader=new FileReader();
    reader.onload=function(){
      var text=String(reader.result||'');
      var raw=text.split(/\r?\n/).map(function(s){return s.trim();}).filter(Boolean);
      if(raw.length)B_FILES.push({name:file.name,size:file.size,lines:raw});
      pending--;
      if(pending===0){renderBFileList();calcBEst();}
    };
    reader.readAsText(file,'utf-8');
  });
}
function renderBFileList(){
  var box=document.getElementById('bFileList');
  if(!box)return;
  if(!B_FILES.length){box.innerHTML='<p class="ph-note fs-10 pad-sm">'+tr('batch_no_files')+'</p>';return;}
  box.innerHTML='';
  B_FILES.forEach(function(f,idx){
    var d=document.createElement('div');d.className='f-row';
    d.innerHTML='<span class="nm">'+escHtml(f.name)+'</span><span class="sz">'+fmtSize(f.size)+' · '+tr('batch_line_n',{n:f.lines.length})+'</span><span class="st ok">'+tr('batch_parsed')+'</span><button class="btn btn-sm" class="btn-remove" type="button">'+tr('batch_remove')+'</button>';
    d.querySelector('button').addEventListener('click',function(){B_FILES.splice(idx,1);renderBFileList();calcBEst();});
    box.appendChild(d);
  });
}
function bPrompts(){
  var seen={},out=[];
  B_FILES.forEach(function(f){f.lines.forEach(function(l){if(!seen[l]){seen[l]=1;out.push(l);}});});
  return out;
}
function bGridCombos(){
  var n=1;
  document.querySelectorAll('#bpane-grid .dim>input[type=checkbox]:checked').forEach(function(c){
    var vals=c.parentElement.querySelectorAll('.vals label.checked');
    n*=Math.max(1,vals.length);
  });
  return n;
}
function bGridDims(){
  var grid={};
  document.querySelectorAll('#bpane-grid .dim').forEach(function(dim){
    var key=dim.querySelector('.dim-name').textContent.trim().split(/\s+/)[0];
    var checked=dim.querySelector('input[type=checkbox]').checked;
    if(checked){
      var vals=[];
      dim.querySelectorAll('.vals label.checked').forEach(function(l){
        var v=l.textContent.trim();
        if(key==='steps'||key==='width'||key==='height')vals.push(parseInt(v,10));
        else if(key==='cfg')vals.push(parseFloat(v));
        else vals.push(v);
      });
      if(vals.length)grid[key]=vals;
    }
  });
  return grid;
}
function calcBEst(){
  var lines=bPrompts().length;
  var groups=bGridCombos();
  var batch=+(document.getElementById('bBatchSize')||{value:1}).value||1;
  var total=lines*groups*batch;
  document.getElementById('bFileStat').textContent=tr('batch_file_stat',{n:B_FILES.length,l:lines});
  document.getElementById('gridCombo').textContent=tr('batch_groups_val',{n:groups});
  document.getElementById('bBatchStat').textContent=batch;
  var e=document.getElementById('bEst');
  e.innerHTML=tr('batch_est_line',{t:total,l:lines,g:groups,b:batch});
  e.className='big-est'+(total>=5000?' red':(total>=500?' yellow':''));
  document.getElementById('bWarn500').classList.toggle('show',total>=500&&total<5000);
  document.getElementById('bWarn5000').classList.toggle('show',total>=5000);
}
var bDrop=document.getElementById('bDropzone'),bInput=document.getElementById('bFileInput');
if(bDrop&&bInput){
  bDrop.addEventListener('click',function(){bInput.click();});
  bInput.addEventListener('change',function(){readBatchFiles(bInput.files);bInput.value='';});
  ['dragover','dragenter'].forEach(function(ev){bDrop.addEventListener(ev,function(e){e.preventDefault();e.stopPropagation();bDrop.style.borderColor='var(--accent)';});});
  ['dragleave','drop'].forEach(function(ev){bDrop.addEventListener(ev,function(e){e.preventDefault();e.stopPropagation();bDrop.style.borderColor='';});});
  bDrop.addEventListener('drop',function(e){readBatchFiles(e.dataTransfer.files);});
}
document.querySelectorAll('#bpane-grid .vals label').forEach(function(l){l.addEventListener('click',function(){l.classList.toggle('checked');calcBEst();});});
document.querySelectorAll('#bpane-grid .dim>input[type=checkbox]').forEach(function(c){c.addEventListener('change',function(){var vals=c.parentElement.querySelectorAll('.vals label');vals.forEach(function(l){l.classList.toggle('checked',c.checked);});calcBEst();});});
var bBatchSel=document.getElementById('bBatchSize');
if(bBatchSel)bBatchSel.addEventListener('change',calcBEst);
calcBEst();
document.querySelectorAll('.tabs .tab').forEach(function(t){t.addEventListener('click',function(){document.querySelectorAll('.tabs .tab').forEach(function(x){x.classList.remove('active');});document.querySelectorAll('.tabpane').forEach(function(x){x.classList.remove('active');});t.classList.add('active');document.getElementById(t.dataset.t).classList.add('active');});});

calcBEst();
/* ---------- 缩放控件 ---------- */
var zooms=[50,75,100,125,150,200],zi=2;var zVal=document.getElementById('zVal');
document.getElementById('zOut').addEventListener('click',function(){zi=Math.max(0,zi-1);zVal.textContent=zooms[zi]+'%';});
document.getElementById('zIn').addEventListener('click',function(){zi=Math.min(zooms.length-1,zi+1);zVal.textContent=zooms[zi]+'%';});

/* ================================================================
   F1-F10: 真实 API 接线（AUDIT_REPORT_2.0 R2 修复）
   原则：UI 结构不动，把模拟数据/模拟执行替换为真实 fetch / SSE
   ================================================================ */

/* ---------- F10: i18n/主题 localStorage 持久化 + 防闪烁 ---------- */
// 防闪烁：在 DOMContentLoaded 前恢复主题
(function(){
  var savedTheme=localStorage.getItem('imm_theme')||'light';
  var savedLang=localStorage.getItem('imm_lang')||'zh-CN';
  document.documentElement.setAttribute('data-theme',savedTheme);
  document.documentElement.setAttribute('data-lang',savedLang);
  if(themeBtn){var ic=themeBtn.querySelector('.ic');if(ic)ic.textContent=savedTheme==='dark'?'◑':'◐';}
  if(langSel){langSel.value=savedLang;}
  applyLang(savedLang);
})();
// 主题切换 → 持久化
themeBtn.onclick=function(){
  var dark=document.documentElement.getAttribute('data-theme')==='dark';
  var newTheme=dark?'light':'dark';
  document.documentElement.setAttribute('data-theme',newTheme);
  var ic=themeBtn.querySelector('.ic');if(ic)ic.textContent=dark?'◐':'◑';
  localStorage.setItem('imm_theme',newTheme);
};
// 语言切换 → 持久化
langSel.addEventListener('change',function(e){
  localStorage.setItem('imm_lang',e.target.value);
  applyLang(e.target.value);
});
// 从 localStorage 恢复语言菜单选中状态
document.querySelectorAll('#langMenu .ip-item').forEach(function(b){
  if(b.dataset.l===localStorage.getItem('imm_lang')){
    document.querySelectorAll('#langMenu .ip-item').forEach(function(x){x.classList.remove('on');});
    b.classList.add('on');
  }
});

/* ---------- API 辅助对象 + 全局 SSE ---------- */
/* CSRF (Double-Submit Cookie)：GET 响应头 X-CSRF-Token 与 httponly csrf_token cookie 同值；
   POST/PUT/DELETE 需带 X-CSRF-Token 头（后端校验 头==cookie，否则 403） */
var _csrfToken=null;
async function _ensureCsrf(){
  if(_csrfToken)return _csrfToken;
  var r=await fetch('/api/health');  // 任意 GET 领取 token
  var t=r.headers.get('X-CSRF-Token');if(t)_csrfToken=t;
  return _csrfToken;
}
var API={
  get:async function(p){
    var r=await fetch('/api'+p);
    var t=r.headers.get('X-CSRF-Token');if(t)_csrfToken=t;  // 每次 GET 刷新本地 token
    return r.json();
  },
  send:async function(p,body,method){
    method=method||'POST';
    var h={'Content-Type':'application/json'};
    var t=await _ensureCsrf();if(t)h['X-CSRF-Token']=t;
    var opts={method:method,headers:h};
    if(body)opts.body=JSON.stringify(body);
    var r=await fetch('/api'+p,opts);
    return r.json();
  },
  put:async function(p,body){return API.send(p,body,'PUT');},
  del:async function(p){return API.send(p,null,'DELETE');},
  post:async function(p,body){return API.send(p,body,'POST');}
};
var evt=new EventSource('/api/events'); // 全局唯一 SSE 连接
var currentTaskId=null;

// SSE 事件处理
evt.addEventListener('connected',function(e){
  console.log('[SSE] Connected');
});
evt.addEventListener('task_status',function(e){
  try{
    var d=JSON.parse(e.data);
    if(d.task_id===currentTaskId||!currentTaskId){
      if(d.progress!==undefined){progFill.style.width=d.progress+'%';phaseText.textContent=trPhase(d.phase||'')+' · '+d.progress+'%';qpPct.textContent=d.progress+'%';}
      if(d.status){
        if(d.status==='completed'){genBtn.disabled=false;timer=null;phaseText.textContent='完成 · '+(d.result?d.result.length:0)+' 张输出';progFill.style.width='100%';qpDot.className='qd';qpPct.style.display='none';qpText.textContent='队列 0·0 · 完成';if(d.result&&d.result.length)renderOutReal(d.result);loadRecent();}
        else if(d.status==='failed'){genBtn.disabled=false;timer=null;phaseText.textContent='失败: '+(d.error||'');progFill.style.width='0%';qpDot.className='qd';qpPct.style.display='none';qpText.textContent='失败';}
        else if(d.status==='cancelled'){genBtn.disabled=false;timer=null;phaseText.textContent='已取消';progFill.style.width='0%';qpDot.className='qd';qpPct.style.display='none';qpText.textContent='已取消';}
        else if(d.status==='processing'){qpDot.className='qd run';qpPct.style.display='';qpText.textContent='生成中';}
      }
    }
  }catch(err){console.warn('[SSE] parse error',err);}
});
evt.addEventListener('heartbeat',function(e){console.log('[SSE] heartbeat');});
evt.addEventListener('preview',function(e){
  try{
    var d=JSON.parse(e.data);
    if(d.b64){
      var img=document.createElement('img');
      img.src='data:image/'+(d.format||'jpg')+';base64,'+d.b64;
      img.style.cssText='max-width:100%;border-radius:6px;margin-top:6px';
      var prog=document.getElementById('genProgress');
      if(prog){var old=prog.querySelector('.preview-img');if(old)old.remove();img.className='preview-img';prog.appendChild(img);}
    }
  }catch(err){console.warn('[SSE] preview parse error',err);}
});
evt.addEventListener('gpu_status',function(e){
  try{
    var d=JSON.parse(e.data);
    var sb=document.querySelector('.sb-gpu');
    if(sb){var f=d.free_vram_gb,t=d.total_vram_gb;sb.textContent=(t&&f!=null)?'VRAM 可用 '+f.toFixed(1)+' / '+t.toFixed(1)+' GB':(f!=null?'VRAM 可用 '+f.toFixed(1)+' GB':'GPU —');}if(d.total_vram_gb){setBar('statGpu',(d.used_vram_gb||0).toFixed(1)+' / '+d.total_vram_gb+' GB',d.total_vram_gb?Math.round((d.used_vram_gb||0)/d.total_vram_gb*100):0);}
  }catch(err){}
});

/* ---------- 系统状态：真实 health / GPU / 资源 ---------- */
function loadHealth(){
  fetch('/api/health').then(function(r){return r.json();}).then(function(h){
    if(!h||h.status!=='ok'){setConn(false);return;}
    setConn(true);
    var av=document.getElementById('aboutVersion');if(av)av.textContent=h.version||'—';
    // 状态栏：队列 + 引擎
    var q=h.queue||{};
    var sbq=document.getElementById('sbQueue');
    if(sbq)sbq.textContent='QUEUE '+(q.processing||0)+'·'+(q.pending||0);
    // 状态栏：GPU（SSE 也会更新）
    var g=h.gpu||{};
    var sbg=document.querySelector('.sb-gpu');
    if(sbg){var f2=g.free_vram_gb,t2=g.total_vram_gb;sbg.textContent=(t2&&f2!=null)?'VRAM 可用 '+f2.toFixed(1)+' / '+t2.toFixed(1)+' GB':(f2!=null?'VRAM 可用 '+f2.toFixed(1)+' GB':(t2?t2.toFixed(1)+' GB total':'GPU —'));}
    renderStatusBars(h);
    renderStatEngines(h.engines||[]);
    renderStatLoras();
  }).catch(function(){setConn(false);});
}
function setConn(ok){
  var dot=document.getElementById('sbConnDot'),txt=document.getElementById('sbConnText');
  if(!dot||!txt)return;
  dot.className='dot '+(ok?'green':'red');
  txt.textContent=ok?'CONN: OK':'CONN: 离线';
}
function renderStatusBars(h){
  // GPU
  var g=h.gpu||{};
  if(g.total_vram_gb){
    var used=((g.used_vram_gb!=null?g.used_vram_gb:(g.total_vram_gb-(g.free_vram_gb||0)))||0);
    var pct=g.total_vram_gb?Math.round(used/g.total_vram_gb*100):0;
    setBar('statGpu',used.toFixed(1)+' / '+g.total_vram_gb+' GB',pct);
  }else{setBar('statGpu','无 GPU 信息',0);}
  // 内存
  var m=h.memory||{};
  if(m.total_gb){setBar('statMem',m.used_gb+' / '+m.total_gb+' GB',Math.round(m.percent||0));}
  else{setBar('statMem','—',0);}
  // 磁盘
  var d=h.disk||{};
  if(d.total_gb){setBar('statDisk',d.used_gb+' / '+d.total_gb+' GB',d.total_gb?Math.round(d.used_gb/d.total_gb*100):0);}
  else{setBar('statDisk','—',0);}
}
function setBar(id,text,pct){
  var v=document.getElementById(id),b=document.getElementById(id+'Bar'),p=document.getElementById(id+'Pct');
  if(v)v.textContent=text;
  if(b)b.style.width=Math.max(0,Math.min(100,pct||0))+'%';
  if(p)p.textContent=(pct||0)+'%';
}
function renderStatEngines(engines){
  var box=document.getElementById('statEngines');
  if(!box)return;
  if(!engines||!engines.length){box.innerHTML='<div class="back-row"><b>无引擎配置</b></div>';return;}
  box.innerHTML='';
  engines.forEach(function(e){
    var d=document.createElement('div');d.className='back-row';
    var st=e.state||(e.ready?'loaded':'unknown');
    var chipTxt=st==='loaded'?'就绪':(st==='loading'?'加载中':(st==='error'?'错误':'未加载'));
    var chipCls=st==='loaded'?'chip ok':(st==='loading'?'chip':'chip red');
    d.innerHTML='<b>'+escHtml(e.display_name)+'</b><span class="text-faint">'+escHtml(st)+'</span><span class="'+chipCls+'">'+chipTxt+'</span>';
    box.appendChild(d);
  });
}
function renderStatLoras(){
  var el=document.getElementById('statLoras'),chip=document.getElementById('statLorasChip');
  if(!el)return;
  fetch('/api/config/loras').then(function(r){return r.json();}).then(function(d){
    var n=(d.loras||[]).length;
    el.textContent='loras/ · '+n+' 个文件';
    if(chip){chip.textContent=n>0?'就绪':'空';chip.className='chip '+(n>0?'ok':'red');}
  }).catch(function(){el.textContent='加载失败';if(chip){chip.textContent='—';}});
}
var statRefreshBtn=document.getElementById('statRefresh');
if(statRefreshBtn)statRefreshBtn.addEventListener('click',function(){loadHealth();});

/* ---------- F1: 生成 + 进度 + 队列球 ---------- */
// 覆盖 startGen → POST /api/generate
function startGenReal(){
  if(timer)return;
  var loraSels=document.querySelectorAll('#loraStack .lora-name');
  var loraSliders=document.querySelectorAll('#loraStack .r2 input[type=range]');
  function loraName(i){var s=loraSels[i];if(!s)return '';var v=s.value;return(v==='— 禁用 —')?'':v;}
  function loraStrength(i){var s=loraSliders[i];return s?(+s.value||0):0;}
  var axisEl=document.querySelector('input[name="axis"]:checked');
  var outPrefix=document.getElementById('outputPrefix');
  var cfg={
    positive_prompt:posPrompt.value||'',
    negative_prompt:negPrompt.value||'',
    cfg:+document.getElementById('cfg').value||1.0,
    steps:+document.getElementById('steps').value||8,
    width:+document.getElementById('width').value||1024,
    height:+document.getElementById('height').value||1024,
    seed:+document.getElementById('seed').value||-1,
    batch_size:+document.getElementById('batchSize').value||1,
    lora_1_name:loraName(0),lora_1_strength:loraStrength(0),
    lora_2_name:loraName(1),lora_2_strength:loraStrength(1),
    lora_3_name:loraName(2),lora_3_strength:loraStrength(2),
    lora_4_name:loraName(3),lora_4_strength:loraStrength(3),
    lora_5_name:loraName(4),lora_5_strength:loraStrength(4),
    lora_6_name:loraName(5),lora_6_strength:loraStrength(5),
    seedvr2_enable:document.getElementById('seedvr2Toggle').checked,
    seedvr2_resolution:+document.getElementById('upscaleRes').value||2048,
    seedvr2_seed:+document.getElementById('upscaleSeed').value||-1,
    seedvr2_color_correction:document.getElementById('colorCorr').value||'lab',
    eses_enable:document.getElementById('esesToggle').checked,
    eses_compare_axis:axisEl?axisEl.value:'horizontal',
    vram_enable:document.getElementById('vramToggle').checked,
    vram_reserved_gb:+document.getElementById('vramGb').value||0.6,
    vram_mode:document.getElementById('vramMode').value||'auto',
    vram_seed:+document.getElementById('vramSeed').value||-1,
    output_format:'png',
    output_prefix:outPrefix?outPrefix.value:'{engine}',
    engine_name:document.getElementById('engineSelect').value
  };
  genBtn.disabled=true;
  genProgress.classList.add('show');
  progFill.style.width='0%';
  phaseText.textContent='提交中…';
  qpDot.className='qd run';qpPct.style.display='';qpText.textContent='提交中';
  API.post('/generate',cfg).then(function(r){
    if(r.task_id){
      currentTaskId=r.task_id;
      phaseText.textContent=r.estimated_time_s?('排队中…（预计 '+(r.estimated_time_s>=60?Math.ceil(r.estimated_time_s/60)+' 分钟':Math.ceil(r.estimated_time_s)+'s')+'）'):'排队中…';
      if(r.warning)console.warn('[Gen] Warning:',r.warning);
    }else{
      genBtn.disabled=false;
      genProgress.classList.remove('show');
      qpDot.className='qd';qpPct.style.display='none';qpText.textContent='错误';
      window.alert('生成失败: '+(r.detail||JSON.stringify(r)));
    }
  }).catch(function(e){
    genBtn.disabled=false;genProgress.classList.remove('show');
    qpDot.className='qd';qpPct.style.display='none';qpText.textContent='错误';
    window.alert('请求失败: '+e);
  });
}
// 覆盖 cancelGen → POST /api/tasks/{id}/cancel
function cancelGenReal(){
  if(!currentTaskId){if(timer){clearInterval(timer);timer=null;}genBtn.disabled=false;phaseText.textContent='已取消';return;}
  API.post('/tasks/'+currentTaskId+'/cancel').then(function(r){
    genBtn.disabled=false;timer=null;
    phaseText.textContent='已取消 (status=cancelled)';
    progFill.style.width='0%';genProgress.classList.remove('show');
    qpDot.className='qd';qpPct.style.display='none';qpText.textContent='已取消';
    currentTaskId=null;
  }).catch(function(e){console.error('[Cancel] error:',e);});
}
// 覆盖 renderOut → 真实输出
function renderOutReal(imgPaths){
  outGrid.innerHTML='';
  if(!imgPaths||!imgPaths.length){outGrid.innerHTML='<p class="ph-note pad-lg">无输出</p>';return;}
  imgPaths.forEach(function(path,i){
    var types=['原图'];
    var c=document.createElement('div');c.className='r-card';c.style.setProperty('--ar','1/1');
    c.innerHTML='<div class="ph-img"><img src="/api/outputs/'+path+'" class="img-fit-lg"><div class="r-actions"><button class="btn btn-sm" type="button" data-act="download">下载</button><button class="btn btn-sm" type="button">收藏</button><button class="btn btn-sm" type="button" data-act="redraw">重绘</button></div></div><div class="r-meta"><span class="r-type">'+escHtml(types[i]||('输出 '+(i+1)))+'</span><b class="r-tt">'+escHtml(path.split('/').pop())+'</b></div>';
    // P2-4 CSP 收紧：内联 onclick 改 data-act + 事件绑定（script-src 'self' 禁止属性式处理器）
    var dlBtn=c.querySelector('button[data-act="download"]');
    if(dlBtn)dlBtn.addEventListener('click',function(){window.open('/api/outputs/'+path,'_blank');});
    var rdBtn=c.querySelector('button[data-act="redraw"]');
    if(rdBtn)rdBtn.addEventListener('click',function(){redrawTask(currentTaskId);});
    outGrid.appendChild(c);
  });
}
// 重绘函数
function redrawTask(taskId){if(!taskId)return;API.post('/tasks/'+taskId+'/redraw').then(function(r){if(r.task_id){currentTaskId=r.task_id;genBtn.disabled=true;genProgress.classList.add('show');progFill.style.width='0%';phaseText.textContent='重绘中…';qpDot.className='qd run';qpPct.style.display='';qpText.textContent='重绘中';}}).catch(function(e){window.alert('重绘失败: '+e);});}
// 覆盖生成按钮事件
genBtn.removeEventListener('click',function(){}); // 移除旧监听
genBtn.onclick=function(){
  var e=estCount();
  function proceed(){precheckEngineThen(startGenReal);}
  if(e.total>=5000){appConfirm('⚠ 将生成 '+e.total+' 张（batch='+e.n+'）。预计 '+Math.ceil(e.total/3000)+' 小时，确认？',{okText:'继续生成',danger:true}).then(function(ok){if(ok)proceed();});return;}
  if(e.total>=500){appConfirm('⚠ 将生成 '+e.total+' 张，预计 '+(e.total*1.5/60).toFixed(0)+' 分钟，确认？',{okText:'继续生成'}).then(function(ok){if(ok)proceed();});return;}
  proceed();
};
// 引擎就绪预检：未加载模型时告知会先自动加载，避免用户对着「排队中」干等
function precheckEngineThen(done){
var eng=document.getElementById('engineSelect').value;
if(!eng){done();return;}
API.get('/engine/engines').then(function(r){
var item=null;
if(r&&r.engines)for(var i=0;i<r.engines.length;i++)if(r.engines[i].name===eng){item=r.engines[i];break;}
if(!item||item.ready){done();return;}
var label=item.display_name||eng;
if(item.state==='error'){appConfirm('引擎「'+label+'」当前为错误状态，请先在设置/引擎中重新加载后再生成。',{okText:'知道了',danger:true}).then(function(){});return;}
appConfirm('引擎「'+label+'」尚未加载模型，生成时会先自动加载（可能耗时数分钟）。是否继续？',{okText:'继续生成'}).then(function(ok){if(ok)done();});
}).catch(function(){done();}); // 状态查询失败不阻塞生成
}
// 覆盖取消按钮
var qCancelBtn=document.getElementById('qCancelBtn');
if(qCancelBtn)qCancelBtn.onclick=function(){cancelGenReal();qpop.classList.remove('show');};

/* ---------- F3: LoRA 下拉 ← 后端资源扫描 ---------- */
var _lorasLoaded=false;
function loadLoras(){
  if(_lorasLoaded)return;
  fetch('/api/config/loras').then(function(r){return r.json();}).then(function(d){
    var sels=document.querySelectorAll('#loraStack .lora-name');
    if(!sels.length)return;
    var items=d.loras||[];
    sels.forEach(function(sel){
      var cur=sel.value;
      sel.innerHTML='<option>— 禁用 —</option>';
      var match=null;
      items.forEach(function(p){var o=document.createElement('option');o.value=p;o.textContent=p.split('/').pop();sel.appendChild(o);if(p.split('/').pop()===cur)match=p;});
      sel.value=match||'— 禁用 —';
    });
    _lorasLoaded=true;
    var h=document.getElementById('scanHint');if(h)h.textContent='loras/ '+d.count+' 个 · 模式 '+(d.mode==='portable'?'portable':'shared');
  }).catch(function(e){console.warn('[LoRA] load failed:',e);});
}
var scanBtn=document.getElementById('scanBtn');
if(scanBtn)scanBtn.addEventListener('click',function(){_lorasLoaded=false;loadLoras();});
/* ---------- F2: 设置顶抽屉（真实配置） ---------- */
function fillSettings(cfg){
  if(!cfg)return;
  var se=document.getElementById('setEngine');
  if(se){
    se.innerHTML='<option value="">请选择引擎</option>';
    var engs=cfg.models&&cfg.models.engines||{};
    Object.keys(engs).forEach(function(k){var o=document.createElement('option');o.value=k;o.textContent=engs[k].display_name||k;se.appendChild(o);});
    se.value=(cfg.models&&cfg.models.default_engine)||'';
  }
  var ec=(cfg.models&&cfg.models.engines&&cfg.models.engines[cfg.models.default_engine])||{};
  var wd=document.getElementById('setWorkflowDir');if(wd)wd.value=ec.workflow_file||'';
  var mm=document.getElementById('setModelMode');if(mm){var ms=cfg.models||{};mm.value=(ms.model_source_mode||'')+' · '+((ms.model_source_mode==='portable'?(ms.portable&&ms.portable.internal_models_dir):(ms.shared&&ms.shared.comfy_models_dir))||'');}
  var sd=document.getElementById('setSeedvr2Dir');if(sd){var ms2=cfg.models||{};sd.value=(ms2.model_source_mode==='portable'?(ms2.portable&&ms2.portable.internal_models_dir):(ms2.shared&&ms2.shared.comfy_models_dir))||'';}
  var hb=document.getElementById('setHeartbeat');if(hb&&cfg.comfy&&cfg.comfy.backends&&cfg.comfy.backends.local)hb.value=String(cfg.comfy.backends.local.health_check_interval_s||30);
  var sp=document.getElementById('setSpawn');if(sp&&cfg.comfy&&cfg.comfy.backends&&cfg.comfy.backends.local)sp.value=String(cfg.comfy.backends.local.auto_spawn_if_dead===true?'true':'false');
  var lb=document.getElementById('setLb');if(lb&&cfg.comfy)lb.value=cfg.comfy.load_balance||'prefer_local';
  var rh=document.getElementById('retentionHint');if(rh&&cfg.history)rh.textContent='db: '+((cfg.history.db_path)||'');
}
var _origOpenSet=openSet;
openSet=function(){
  _origOpenSet();
  fetch('/api/config').then(function(r){return r.json();}).then(function(cfg){
    fillSettings(cfg);
  }).catch(function(e){console.warn('[Config] load failed:',e);});
};
// 设置抽屉：切换默认引擎 → 同步主界面
var setEngineEl=document.getElementById('setEngine');
if(setEngineEl)setEngineEl.addEventListener('change',function(){
  if(!this.value)return;
  var es=document.getElementById('engineSelect');
  if(es&&ENGINES[this.value]){es.value=this.value;es.dispatchEvent(new Event('change'));syncEngMenu();}
});
// 关闭设置抽屉时保存推理默认值 → PUT /api/config
document.getElementById('setClose').addEventListener('click',function(){
  var update={inference:{default_steps:+document.getElementById('steps').value||10,default_cfg:+document.getElementById('cfg').value||1.0}};
  API.put('/config',update).then(function(r){console.log('[Config] saved:',r);}).catch(function(e){console.warn('[Config] save failed:',e);});
  setD.classList.remove('open');setSc.classList.remove('show');
});

/* ---------- F6: 历史左抽屉（真实渲染 + 筛选/分页/详情） ---------- */
var _histPage=1,_histQ='',_histStatus='',_histEngine='',_curDetailTask=null;
function renderHist(){
  var tbody=document.getElementById('histRows');if(!tbody)return;
  var qs='/api/tasks?page='+_histPage+'&page_size=20';
  if(_histStatus)qs+='&status='+encodeURIComponent(_histStatus);
  if(_histEngine)qs+='&engine='+encodeURIComponent(_histEngine);
  if(_histQ)qs+='&q='+encodeURIComponent(_histQ);
  fetch(qs).then(function(r){return r.json();}).then(function(r){
    tbody.innerHTML='';
    var list=r.tasks||[];
    if(!list.length){tbody.innerHTML='<tr><td colspan="4" class="ph-note pad-lg">暂无历史记录</td></tr>';}
    list.forEach(function(t){
      var rowEl=document.createElement('tr');
      var st=t.status||'';
      var chip=st==='completed'?'ok':(st==='failed'?'red':'warn');
      rowEl.innerHTML='<td><div class="th">'+(t.output_count>0?t.output_count+' 张':'—')+'</div></td>'+
        '<td class="pro">'+escHtml(t.prompt||'(无提示词)')+'<br><span class="fs-9 text-faint">'+escHtml(engLabel(t.engine))+'</span></td>'+
        '<td><span class="chip '+chip+'">'+tr('st_'+st)+'</span></td>'+
        '<td><button class="btn btn-sm" type="button">详情</button></td>';
      rowEl.addEventListener('click',function(){showHistDetail(t);});
      rowEl.querySelector('button').addEventListener('click',function(e){e.stopPropagation();showHistDetail(t);});
      tbody.appendChild(rowEl);
    });
    var total=r.total||0,tp=r.total_pages||1;
    document.getElementById('histTotal').textContent=tr('hist_total',{n:total});
    document.getElementById('histCount').textContent=tr('hist_page',{p:_histPage,tp:tp});
    var prev=document.getElementById('histPrev'),next=document.getElementById('histNext');
    if(prev)prev.disabled=_histPage<=1;
    if(next)next.disabled=_histPage>=tp;
  }).catch(function(e){console.warn('[History] load failed:',e);tbody.innerHTML='<tr><td colspan="4" class="ph-note pad-lg">加载失败</td></tr>';});
}
function showHistDetail(t){
  document.getElementById('histList').classList.add('hide');
  document.getElementById('histDetail').classList.add('show');
  var gc=t.generation_config||{};
  var st=t.status||'';
  document.getElementById('ddEngine').textContent=engLabel(t.engine);
  document.getElementById('ddStatus').textContent=tr('st_'+st);
  document.getElementById('ddMode').textContent=t.mode||'txt2img';
  document.getElementById('ddPrompt').textContent=t.prompt||tr('no_prompt');
  document.getElementById('ddDim').textContent=(gc.width||'?')+'×'+(gc.height||'?')+' · seed '+(gc.seed===undefined||gc.seed===null?'—':gc.seed);
  document.getElementById('ddTime').textContent=(t.processing_time_s?t.processing_time_s+'s · ':'')+(t.created_at||'');
  document.getElementById('ddCfgSteps').textContent=(gc.cfg===undefined||gc.cfg===null?'?':gc.cfg)+' · '+(gc.steps===undefined||gc.steps===null?'?':gc.steps);
  var nLora=0;['lora_1_name','lora_2_name','lora_3_name','lora_4_name','lora_5_name','lora_6_name'].forEach(function(k){if(gc[k])nLora++;});
  document.getElementById('ddLora').textContent=(nLora?nLora+' 层':'—')+' · '+(gc.seedvr2_enable?('SeedVR2 '+(gc.seedvr2_resolution||'?')):'SeedVR2 off')+' · '+(gc.eses_enable?('Eses '+(gc.eses_compare_axis||'h')):'Eses off');
  var thumbs=document.getElementById('ddThumbs');
  thumbs.innerHTML=t.output_count>0
    ?'<div class="th th-empty">'+tr('out_count',{n:t.output_count})+'</div>'
    :'<div class="th th-empty">'+tr('no_preview')+'</div>';
  _curDetailTask=t;
}
document.getElementById('ddRedraw').addEventListener('click',function(){if(_curDetailTask)redrawTask(_curDetailTask.task_id);showHistList();});
document.getElementById('ddSavePreset').addEventListener('click',function(){
  if(!_curDetailTask)return;
  var gc=_curDetailTask.generation_config||{};
  var cfg={positive_prompt:_curDetailTask.prompt||'',cfg:gc.cfg,steps:gc.steps,width:gc.width,height:gc.height,seed:gc.seed===undefined?-1:gc.seed};
  API.post('/presets',{engine_name:_curDetailTask.engine||'z_image_turbo_native',name:'任务 '+String(_curDetailTask.task_id).substring(0,8),config:cfg}).then(function(){window.alert('已保存为预设');}).catch(function(e){window.alert('保存失败: '+e);});
});
document.getElementById('ddZip').addEventListener('click',function(){if(_curDetailTask)window.open('/api/tasks/export?ids='+_curDetailTask.task_id,'_blank');});
var _origShowHistList=showHistList;
showHistList=function(){_origShowHistList();renderHist();};
document.getElementById('histSearch').addEventListener('input',function(){
  var me=this;clearTimeout(window._histTimer);
  window._histTimer=setTimeout(function(){_histQ=me.value.trim();_histPage=1;renderHist();},300);
});
document.getElementById('histStatus').addEventListener('change',function(){_histStatus=this.value;_histPage=1;renderHist();});
document.getElementById('histEngine').addEventListener('change',function(){_histEngine=this.value;_histPage=1;renderHist();});
document.getElementById('histPrev').addEventListener('click',function(){if(_histPage>1){_histPage--;renderHist();}});
document.getElementById('histNext').addEventListener('click',function(){_histPage++;renderHist();});
// 批量删除：失败 / 排队中 / 进行中 / 已取消
function fetchAllTaskIds(status){
  var all=[],page=1;
  function one(){
    var q='/api/tasks?page='+page+'&page_size=200'+(status?'&status='+encodeURIComponent(status):'');
    return fetch(q).then(function(r){return r.json();}).then(function(d){
      (d.tasks||[]).forEach(function(t){if(t.task_id)all.push(t.task_id);});
      if(page*200<(d.total||0)){page++;return one();}
      return all;
    });
  }
  return one();
}
function deleteTaskIds(ids){
  if(!ids||!ids.length)return Promise.resolve({deleted:0});
  return API.del('/tasks?task_ids='+ids.map(encodeURIComponent).join('&task_ids='));
}
document.getElementById('histPurge').addEventListener('click',function(){
  var statuses=['failed','pending','processing','cancelled'],all=[];
  Promise.all(statuses.map(function(s){return fetchAllTaskIds(s).then(function(ids){all=all.concat(ids);});})).then(function(){
    var uniq=all.filter(function(v,i){return all.indexOf(v)===i;});
    if(!uniq.length){appConfirm('没有可清理的记录（失败 / 排队中 / 进行中 / 已取消）',{okText:'知道了'}).then(function(){});return;}
    appConfirm('将批量删除 '+uniq.length+' 条记录（失败 / 排队中 / 进行中 / 已取消），不可恢复。确认？',{okText:'删除',danger:true}).then(function(ok){
      if(!ok)return;
      deleteTaskIds(uniq).then(function(r){
        appConfirm('已删除 '+((r&&r.deleted)||uniq.length)+' 条记录',{okText:'知道了'}).then(function(){});
        _histPage=1;renderHist();loadRecent();loadQueueSummary();
      }).catch(function(e){appConfirm('删除失败: '+e,{okText:'知道了',danger:true}).then(function(){});});
    });
  });
});
// 清除全部历史
function updateHistPurgeState(){
  var btn=document.getElementById('histPurge');if(!btn)return;
  var statuses=['failed','pending','processing','cancelled'],pending=statuses.length,total=0;
  statuses.forEach(function(s){
    fetch('/api/tasks?page=1&page_size=1&status='+encodeURIComponent(s)).then(function(r){return r.json();}).then(function(d){
      total+=(d.total||0);pending--;if(pending<=0)btn.disabled=total===0;
    }).catch(function(){pending--;if(pending<=0)btn.disabled=total===0;});
  });
}
var _histPurgePending=0;
document.getElementById('histClear').addEventListener('click',function(){
  fetchAllTaskIds(null).then(function(ids){
    if(!ids.length){appConfirm('当前没有历史记录',{okText:'知道了'}).then(function(){});return;}
    appConfirm('将清除全部 '+ids.length+' 条历史记录（含成功记录），不可恢复。确认？',{okText:'清除',danger:true}).then(function(ok){
      if(!ok)return;
      deleteTaskIds(ids).then(function(r){
        appConfirm('已清除 '+((r&&r.deleted)||ids.length)+' 条记录',{okText:'知道了'}).then(function(){});
        _histPage=1;renderHist();loadRecent();loadQueueSummary();
      }).catch(function(e){appConfirm('清除失败: '+e,{okText:'知道了',danger:true}).then(function(){});});
    });
  });
});

/* ---------- F5: 预设右抽屉（真实渲染 + 应用/编辑/保存 + 多选批量删除） ---------- */
var _editPresetId=null;
var _selPresets={};
function updatePSelUI(){
  var ids=Object.keys(_selPresets).filter(function(k){return _selPresets[k];});
  var cnt=document.getElementById('pSelCount');if(cnt)cnt.textContent=tr('sel_count',{n:ids.length});
  var del=document.getElementById('pBatchDel');if(del)del.disabled=ids.length===0;
  var sa=document.getElementById('pSelectAll');
  if(sa){var all=document.querySelectorAll('#pList .p-check input');sa.textContent=(all.length&&ids.length===all.length)?tr('cancel_select_all'):tr('select_all');}
}
function renderPresets(){
  var pl=document.getElementById('pList');if(!pl)return;
  fetch('/api/presets').then(function(r){return r.json();}).then(function(presets){
    pl.innerHTML='';
    // 清理已删除预设的残留选中
    var live={};presets.forEach(function(p){live[p.id]=1;});
    Object.keys(_selPresets).forEach(function(k){if(!live[k])delete _selPresets[k];});
    if(!presets||!presets.length){pl.innerHTML='<p class="ph-note fs-11 pad-md grid-span">'+tr('presets_empty')+'</p>';updatePSelUI();return;}
    presets.forEach(function(p){
      var cfg=p.config||{};
      var chips='<span class="eng">'+engLabel(p.engine_name)+'</span>';
      if(cfg.steps!==undefined&&cfg.steps!==null)chips+='<span>'+cfg.steps+' steps</span>';
      if(cfg.cfg!==undefined&&cfg.cfg!==null)chips+='<span>cfg '+cfg.cfg+'</span>';
      if(cfg.width&&cfg.height)chips+='<span>'+cfg.width+'×'+cfg.height+'</span>';
      var c=document.createElement('div');c.className='p-card'+( _selPresets[p.id]?' sel':'');
      c.innerHTML='<label class="p-check"><input type="checkbox" data-id="'+p.id+'"'+( _selPresets[p.id]?' checked':'')+' aria-label="选择预设"><span></span></label>'+
        '<div class="nm">'+escHtml((p.name||tr('unnamed')).substring(0,20))+'</div>'+
        '<p class="ds">'+engLabel(p.engine_name)+'</p>'+
        '<div class="param-chips">'+chips+'</div>'+
        '<div class="acts"><button class="btn btn-sm ap" type="button">'+tr('btn_apply')+'</button><button class="btn btn-sm ed" type="button">'+tr('btn_edit')+'</button><button class="btn btn-sm del" class="text-danger" type="button">'+tr('btn_delete')+'</button></div>';
      c.querySelector('.p-check input').addEventListener('change',function(){
        var chk=this;
        if(chk.checked){_selPresets[p.id]=true;c.classList.add('sel');}
        else{delete _selPresets[p.id];c.classList.remove('sel');}
        updatePSelUI();
      });
      c.querySelector('.ap').addEventListener('click',function(){applyPreset(p);});
      c.querySelector('.ed').addEventListener('click',function(){editPreset(p);});
      c.querySelector('.del').addEventListener('click',function(){
        appConfirm(tr('preset_del_confirm',{n:p.name||''}),{okText:tr('btn_delete'),danger:true}).then(function(ok){
          if(!ok)return;
          API.del('/presets/'+p.id).then(function(){renderPresets();}).catch(function(e){appConfirm(tr('preset_del_fail',{e:e}),{okText:tr('btn_got_it'),danger:true}).then(function(){});});
        });
      });
      pl.appendChild(c);
    });
    updatePSelUI();
  }).catch(function(e){console.warn('[Presets] load failed:',e);pl.innerHTML='<p class="ph-note fs-11 pad-md grid-span">'+tr('load_failed')+'</p>';});
}
var pSelectAllBtn=document.getElementById('pSelectAll');
if(pSelectAllBtn)pSelectAllBtn.addEventListener('click',function(){
  var all=document.querySelectorAll('#pList .p-check input');
  var selAll=all.length&&all.length===Object.keys(_selPresets).filter(function(k){return _selPresets[k];}).length;
  all.forEach(function(chk){
    chk.checked=!selAll;
    var card=chk.closest('.p-card');var id=+chk.dataset.id;
    if(!selAll){_selPresets[id]=true;card.classList.add('sel');}
    else{delete _selPresets[id];card.classList.remove('sel');}
  });
  updatePSelUI();
});
var pBatchDelBtn=document.getElementById('pBatchDel');
if(pBatchDelBtn)pBatchDelBtn.addEventListener('click',function(){
  var ids=Object.keys(_selPresets).filter(function(k){return _selPresets[k];}).map(Number);
  if(!ids.length)return;
  appConfirm(tr('preset_del_confirm_batch',{n:ids.length}),{okText:tr('btn_delete'),danger:true}).then(function(ok){
    if(!ok)return;
    API.del('/presets?ids='+ids.join(',')).then(function(r){
      _selPresets={};
      appConfirm(tr('presets_deleted',{n:(r&&r.deleted)||ids.length}),{okText:tr('btn_got_it')}).then(function(){});
      renderPresets();
    }).catch(function(e){appConfirm(tr('preset_del_fail',{e:e}),{okText:tr('btn_got_it'),danger:true}).then(function(){});});
  });
});
function applyPreset(p){
  if(!p)return;
  function doApply(cfg,eng){
    var es=document.getElementById('engineSelect');
    if(eng&&ENGINES[eng]&&es){es.value=eng;es.dispatchEvent(new Event('change'));syncEngMenu();}
    if(cfg.steps!==undefined&&cfg.steps!==null)document.getElementById('steps').value=cfg.steps;
    if(cfg.cfg!==undefined&&cfg.cfg!==null)document.getElementById('cfg').value=cfg.cfg;
    if(cfg.width!==undefined&&cfg.width!==null)document.getElementById('width').value=cfg.width;
    if(cfg.height!==undefined&&cfg.height!==null)document.getElementById('height').value=cfg.height;
    if(cfg.seed!==undefined&&cfg.seed!==null)document.getElementById('seed').value=cfg.seed;
    updateEst();
    appConfirm(tr('preset_applied',{n:p.name||''}),{okText:tr('btn_got_it')}).then(function(){});
  }
  if(p.id){API.post('/presets/'+p.id+'/apply',{}).then(function(r){doApply(r.config||{},r.engine_name||p.engine_name);}).catch(function(e){appConfirm(tr('preset_apply_fail',{e:e}),{okText:tr('btn_got_it')}).then(function(){});});}
  else{doApply(p.config||{},p.engine_name||'');}
}
function editPreset(p){
  _editPresetId=p.id||null;
  document.getElementById('pName').value=p.name||'';
  var pEng=document.getElementById('pEngine');
  if(pEng){
    pEng.innerHTML='';
    Object.keys(ENGINES).forEach(function(k){var o=document.createElement('option');o.value=k;o.textContent=ENGINES[k];pEng.appendChild(o);});
    if(ENGINES[p.engine_name])pEng.value=p.engine_name;
  }
  document.getElementById('pDesc').value=tr('param_json')+JSON.stringify(p.config||{});
  showPEdit();
}
var _origShowPList=showPList;
showPList=function(){_origShowPList();renderPresets();};
// 保存预设（新建 POST / 编辑 PUT）→ 真实接口
document.getElementById('pSave').addEventListener('click',function(){
  var name=document.getElementById('pName').value||tr('preset_default_name',{n:Date.now()%1000});
  var pEng=document.getElementById('pEngine');
  var eng=(pEng&&pEng.value)||document.getElementById('engineSelect').value;
  var cfg={positive_prompt:posPrompt.value,cfg:+document.getElementById('cfg').value||1.0,steps:+document.getElementById('steps').value||8,width:+document.getElementById('width').value||1024,height:+document.getElementById('height').value||1024,seed:+document.getElementById('seed').value||-1};
  if(_editPresetId){
    API.put('/presets/'+_editPresetId,{name:name,config:cfg}).then(function(){showPList();appConfirm(tr('preset_updated'),{okText:tr('btn_got_it')}).then(function(){});}).catch(function(e){appConfirm(tr('save_failed',{e:e}),{okText:tr('btn_got_it')}).then(function(){});});
  }else{
    API.post('/presets',{engine_name:eng,name:name,config:cfg}).then(function(){showPList();appConfirm(tr('preset_saved_ok'),{okText:tr('btn_got_it')}).then(function(){});}).catch(function(e){appConfirm(tr('save_failed',{e:e}),{okText:tr('btn_got_it')}).then(function(){});});
  }
});

/* ---------- F7: 图库顶抽屉（真实渲染 + 标签映射） ---------- */
renderGallery=function(filter){
  filter=filter||'全部';
  gMasonry.innerHTML='';
  var f=FILTER_MAP[filter]||null;
  fetch('/api/outputs?page=1&page_size=50').then(function(r){return r.json();}).then(function(r){
    var list=(r.outputs||[]).filter(function(out){return !f||out.output_type===f;});
    if(!list.length){gMasonry.innerHTML='<p class="ph-note pad-lg">'+tr('no_images')+'</p>';return;}
    list.forEach(function(out,idx){
      var d=document.createElement('div');d.className='g-card';
      var ar=(out.width&&out.height)?out.width+'/'+out.height:'1/1';
      d.style.setProperty('--ar',ar);
      d.innerHTML='<span class="g-type">'+escHtml(typeLabel(out.output_type)||tr('gen_result'))+'</span><div class="ph"><img src="/api/outputs/'+out.path+'" class="img-fit-sm"></div><div class="g-meta"><b>'+escHtml((out.prompt||tr('gen_result')).substring(0,20))+'</b><span>'+escHtml(engLabel(out.engine))+' · '+(out.created_at?String(out.created_at).substring(5,16):'')+'</span></div>';
      // P2-4 CSP 收紧：onerror 属性改 JS 属性绑定
      var gImg=d.querySelector('.ph img');
      if(gImg)gImg.onerror=function(){this.parentElement.textContent=tr('load_failed');};
      d.addEventListener('click',function(){openViewerReal(out,list,idx);});
      gMasonry.appendChild(d);
    });
  }).catch(function(e){console.warn('[Gallery] load failed:',e);gMasonry.innerHTML='<p class="ph-note pad-lg">加载失败</p>';});
};
function openViewerReal(out,list,idx){
  _curViewer=out;
  if(list){_navList=list;_navIdx=(idx===undefined||idx===null)?-1:idx;}
  else{_navList=null;_navIdx=-1;}
  zoom=100;compare=false;
  vTitle.textContent=(out.prompt||'生成结果');
  vSeed.textContent=(out.seed===undefined||out.seed===null||out.seed===-1)?'seed 随机':'seed '+out.seed;
  // 底部信息栏：prompt（2 行截断，可展开）+ 参数 chips
  var pt=document.getElementById('vPromptText');
  if(pt){pt.textContent=out.prompt||'';pt.title=out.prompt||'';}
  var info=document.getElementById('vInfo');
  if(info)info.classList.remove('expanded');
  var toggle=document.getElementById('vPromptToggle');
  if(toggle)toggle.textContent=((out.prompt||'').length>70?'展开':'');
  var parts=[];
  parts.push(engLabel(out.engine));
  parts.push(typeLabel(out.output_type)||'');
  if(out.width&&out.height)parts.push(out.width+'×'+out.height);
  if(out.created_at)parts.push(String(out.created_at).substring(5,16));
  vMeta.innerHTML=parts.filter(Boolean).map(function(p){return '<span class="m-chip">'+escHtml(p)+'</span>';}).join('');
  updateNavUI();
  viewer.classList.add('show');
  renderImg();
}
function navViewer(d){
  if(!_navList||!_navList.length)return;
  var i=_navIdx+d;
  if(i<0||i>=_navList.length)return;
  openViewerReal(_navList[i],_navList,i);
}
function updateNavUI(){
  var p=document.getElementById('vPrev'),n=document.getElementById('vNext'),ix=document.getElementById('vIdx');
  if(ix)ix.textContent=(_navList&&_navList.length>1)?((_navIdx+1)+' / '+_navList.length):'';
  if(p)p.disabled=!_navList||_navIdx<=0;
  if(n)n.disabled=!_navList||_navIdx>=_navList.length-1;
}
function renderImgReal(out){_curViewer=out;renderImg();}
/* 覆盖原 mock renderImg：全屏大图 + 对比模式 */
renderImg=function(){
  vImg.style.transform='scale('+(zoom/100)+')';
  var out=_curViewer;
  if(compare&&out){
    vImg.className='v-img split-view';
    var basePath=out.path;
    var comparePath=basePath.replace(/\.png$/i,'_compare.png');
    vImg.innerHTML=
      '<div class="half"><span class="label">Original</span>'+
      '<img src="/api/outputs/'+basePath+'" alt="原图"></div>'+
      '<div class="divider"></div>'+
      '<div class="half"><span class="label">Compare</span>'+
      '<img src="/api/outputs/'+comparePath+'" alt="对比图"></div>';
  // P2-4 CSP 收紧：onerror 属性改 JS 属性绑定
  var cmpFail=vImg.querySelector('img[alt="对比图"]');
  if(cmpFail)cmpFail.onerror=function(){this.parentNode.style.display='none';};
  }else if(compare){vImg.innerHTML='<div class="half"><span class="label">Compare</span><span class="viewer-muted">无对比数据</span></div>';}
  else{
    vImg.className='v-img';
    vImg.innerHTML=out?'<img src="/api/outputs/'+out.path+'" alt="生成结果">':'<span class="viewer-preview">PREVIEW</span>';
  }
  vZoomVal.textContent=zoom+'%';
  document.getElementById('vCompare').classList.toggle('on',compare);
};

/* ---------- F9: 系统状态顶抽屉 ---------- */
var _origOpenStat=openStat;
openStat=function(){
  _origOpenStat();
  // 从后端加载系统状态
  fetch('/api/health').then(function(r){return r.json();}).then(function(h){
    var sd=document.getElementById('statDrawer');if(!sd)return;
    var gpu=h.gpu||{};
    // 查找或创建状态信息容器
    var infoBox=sd.querySelector('.stat-info');
    if(!infoBox){
      infoBox=document.createElement('div');infoBox.className='stat-info';infoBox.style.padding='16px';
      sd.querySelector('.ov-body').prepend(infoBox);
    }
    infoBox.innerHTML=
      '<p><b>状态:</b> '+h.status+'</p>'+
      '<p><b>版本:</b> '+(h.version||'')+'</p>'+
      '<p><b>GPU:</b> '+(gpu.name||'Unknown')+'</p>'+
      '<p><b>VRAM:</b> '+(gpu.total_vram_gb||0).toFixed(1)+' GB 总量 / '+(gpu.free_vram_gb||0).toFixed(1)+' GB 可用'+((gpu.used_vram_gb!=null)?' · '+(gpu.used_vram_gb||0).toFixed(1)+' GB 已用':'')+'</p>'+
      '<p><b>引擎:</b> '+(h.engines?h.engines.map(function(e){return e.display_name||e.name}).join(', '):'无')+'</p>'+
      '<p><b>时间:</b> '+new Date(h.timestamp*1000).toLocaleString()+'</p>';
  }).catch(function(e){console.warn('[Health] failed:',e);});
};

/* ---------- F8: 批量提交 + 进度轮询（真实 API） ---------- */
function collectBaseConfig(){
  return {
    positive_prompt:document.getElementById('posPrompt').value||'',
    negative_prompt:document.getElementById('negPrompt').value||'',
    cfg:+document.getElementById('cfg').value||1.0,
    steps:+document.getElementById('steps').value||8,
    width:+document.getElementById('width').value||1024,
    height:+document.getElementById('height').value||1024,
    seed:-1,
    batch_size:+(document.getElementById('bBatchSize')||{value:1}).value||1,
    seedvr2_enable:document.getElementById('seedvr2Toggle').checked,
    seedvr2_resolution:+(document.getElementById('upscaleRes')||{value:2048}).value||2048,
    eses_enable:document.getElementById('esesToggle').checked,
    vram_enable:document.getElementById('vramToggle').checked,
    vram_reserved_gb:+(document.getElementById('vramGb')||{value:0.6}).value||0.6,
    engine_name:document.getElementById('engineSelect').value
  };
}
var bSubmitBtn=document.getElementById('bSubmit');
if(bSubmitBtn){
  bSubmitBtn.addEventListener('click',function(){
    var prompts=bPrompts();
    if(!prompts.length){window.alert('请先添加 Prompt 文件');return;}
    var grid=bGridDims();
    bSubmitBtn.disabled=true;
    API.post('/generate/batch',{prompts:prompts,grid_dimensions:grid,base_config:collectBaseConfig()}).then(function(r){
      if(r.batch_id){
        try{localStorage.setItem('imm_last_batch',r.batch_id);}catch(e){}
        window.alert('批量任务已提交: '+r.total_tasks+' 个任务 (batch_id='+r.batch_id.substring(0,8)+')');
        renderBatchQueue(r.batch_id);
      }else{
        window.alert('批量提交失败: '+((r.error&&r.error.message)||r.detail||'未知错误'));
      }
    }).catch(function(e){window.alert('批量提交失败: '+e);}).then(function(){bSubmitBtn.disabled=false;});
  });
}
var bCancelBtn=document.getElementById('bCancel');
if(bCancelBtn)bCancelBtn.addEventListener('click',function(){document.getElementById('batchDrawer').classList.remove('open');});
var B_BATCH_POLL=null;
function renderBatchQueue(batchId){
  var box=document.getElementById('bQueueList');
  if(!box)return;
  var bid=batchId||null;
  if(!bid){try{bid=localStorage.getItem('imm_last_batch')||null;}catch(e){}}
  if(!bid){box.innerHTML='<p class="ph-note fs-10 pad-sm2">'+tr('batch_none')+'</p>';return;}
  box.innerHTML='<p class="ph-note fs-10 pad-sm2">'+tr('batch_querying',{id:bid.substring(0,8)})+'</p>';
  API.get('/tasks/batch/'+bid).then(function(r){
    if(r.batch_id){
      var pct=r.progress_pct||0;
      var done=(r.completed+r.failed+r.cancelled)>=r.total;
      box.innerHTML='<div class="qi-main"><div class="qi-title">'+tr('batch_title_line',{id:bid.substring(0,8),n:r.total})+'</div><div class="qi-sub">'+tr('batch_status_line',{c:r.completed,p:r.processing,q:r.pending,f:r.failed,x:r.cancelled})+'</div><div class="progress"><i data-qi-bar></i></div><div class="qi-pct">'+pct+'%</div></div>';
      var qiBar=box.querySelector('[data-qi-bar]');if(qiBar)qiBar.style.width=pct+'%';
      if(!done){clearTimeout(B_BATCH_POLL);B_BATCH_POLL=setTimeout(function(){renderBatchQueue(bid);},2000);}
      else{loadRecent();}
    }else{
      box.innerHTML='<p class="ph-note fs-10 pad-sm2">'+escHtml(r.detail||tr('batch_not_found'))+'</p>';
      try{localStorage.removeItem('imm_last_batch');}catch(e){}
    }
  }).catch(function(){box.innerHTML='<p class="ph-note fs-10 pad-sm2">'+tr('batch_query_fail')+'</p>';});
}


/* ---------- F3: LoRA 下拉从后端资源扫描填充 ---------- */
// 页面加载时从 /api/config 获取 LoRA 列表
fetch('/api/config').then(function(r){return r.json();}).then(function(cfg){
  // 尝试从配置中获取 LoRA 列表（如果后端提供了资源扫描接口）
  // 目前 LoRA 选项保持前端默认，后续可扩展
  console.log('[Init] Config loaded for LoRA dropdown');
}).catch(function(e){console.warn('[Init] Config load failed:',e);});

/* ================================================================
   F11-F13: 全局数据 + 初始化（真实数据源）
   原则：所有面板内容都来自后端接口，不再使用原型硬编码示例
   ================================================================ */
var ENGINES={};        // engine key → display_name（来自 /api/config）
var TYPE_LABELS={original:'type_original',upscaled:'type_upscaled',compare:'type_compare'};
function typeLabel(k){return tr(TYPE_LABELS[k]||k)||k;}
var FILTER_MAP={'全部':null,'原图':'original','超分':'upscaled','对比图':'compare'};
var _CFG=null;         // 最近一次 /api/config 快照

function engLabel(k){return ENGINES[k]||k||'—';}

/* ---------- F14: 主题色切换（24 预设 + 自定义，localStorage 持久化） ---------- */
var ACCENTS=[
['蜜桃橙','#e8822a','#cf6e1a'],['橙焰','#f97316','#ea580c'],['琥珀','#f59e0b','#d97706'],['柠檬','#eab308','#ca8a04'],
['紫罗兰','#7c5fd6','#6b5bb8'],['靛蓝','#6366f1','#4f46e5'],['宝蓝','#3b82f6','#2563eb'],['天蓝','#0ea5e9','#0284c7'],
['青色','#06b6d4','#0891b2'],['青绿','#14b8a6','#0d9488'],['翡翠','#10b981','#059669'],['苔绿','#84cc16','#65a30d'],
['森林','#22c55e','#16a34a'],['朱红','#ef4444','#dc2626'],['玫红','#f43f5e','#e11d48'],['洋红','#ec4899','#db2777'],
['紫红','#d946ef','#c026d3'],['葡萄紫','#a855f7','#9333ea'],['藕荷','#c084fc','#a855f7'],['深紫','#8b5cf6','#7c3aed'],
['石板','#64748b','#475569'],['钢蓝','#475569','#334155'],['海蓝','#0f766e','#115e59'],['珊瑚','#fb7185','#f43f5e']
];
function renderPalette(){
  var grid=document.getElementById('palGrid');if(!grid)return;
  grid.innerHTML='';
  ACCENTS.forEach(function(a){
    var b=document.createElement('button');
    b.className='sw';b.type='button';b.title=a[0];b.dataset.p=a[1];b.dataset.a=a[2];
    b.style.background=a[1];
    b.addEventListener('click',function(){applyAccent(a[1],a[2]);});
    grid.appendChild(b);
  });
  syncPalette();
}
function applyAccent(primary,accent){
  var root=document.documentElement;
  root.style.setProperty('--seed-primary',primary);
  root.style.setProperty('--seed-accent',accent||primary);
  var dot=document.getElementById('palDot');if(dot)dot.style.background=primary;
  var pc=document.getElementById('palCustom');if(pc)pc.value=primary;
  try{localStorage.setItem('imm_accent',JSON.stringify([primary,accent||primary]));}catch(e){}
  syncPalette();
}
function syncPalette(){
  var cur=(document.documentElement.style.getPropertyValue('--seed-primary')||'#e8822a').trim().toLowerCase();
  document.querySelectorAll('#palGrid .sw').forEach(function(b){b.classList.toggle('on',b.dataset.p.toLowerCase()===cur);});
}
function initAccent(){
  var saved=null;try{saved=JSON.parse(localStorage.getItem('imm_accent')||'null');}catch(e){}
  if(saved&&saved[0]){
    var LEGACY={'#fdba74':'#e8822a','#fb923c':'#cf6e1a','#7c5fd6':'#e8822a','#6b5bb8':'#cf6e1a','#ef6d1c':'#cf6e1a','#f98a25':'#e8822a'};
    var s0=saved[0].toLowerCase(),s1=(saved[1]||'').toLowerCase();
    if(LEGACY[s0]){s0=LEGACY[s0];s1=LEGACY[s1]||s0;}
    applyAccent(s0,s1);
  }
  else{applyAccent('#e8822a','#cf6e1a');}
}
var palBtn=document.getElementById('palBtn'),palPop=document.getElementById('palPop');
if(palBtn)palBtn.addEventListener('click',function(e){
  e.stopPropagation();
  engMenu.classList.remove('show');langMenu.classList.remove('show');
  palPop.classList.toggle('show');
});
var palCustom=document.getElementById('palCustom');
if(palCustom)palCustom.addEventListener('input',function(){applyAccent(this.value,this.value);});
document.addEventListener('click',function(e){
  if(!e.target.closest('#palBtn')&&!e.target.closest('#palPop')){if(palPop)palPop.classList.remove('show');}
});
document.addEventListener('keydown',function(e){if(e.key==='Escape'&&palPop)palPop.classList.remove('show');});

/* ---------- F15: 标题艺术字体切换（localStorage 持久化） ---------- */
var FONTS=[
  {name:'现代无衬线',desc:'Inter · 系统默认',fam:'var(--sans)'},
  {name:'思源宋体',desc:'优雅衬线 · Noto Serif SC',fam:'"Noto Serif SC",serif'},
  {name:'站酷小薇',desc:'文艺手写 · ZCOOL XiaoWei',fam:'"ZCOOL XiaoWei","Noto Serif SC",serif'},
  {name:'马善政楷书',desc:'毛笔书法 · Ma Shan Zheng',fam:'"Ma Shan Zheng",cursive'}
];
function renderFontList(){
  var box=document.getElementById('fontList');if(!box)return;
  box.innerHTML='';
  FONTS.forEach(function(f,i){
    var b=document.createElement('button');
    b.className='font-item';b.type='button';b.style.fontFamily=f.fam;
    b.innerHTML=f.name+'<span class="fd">'+f.desc+'</span>';
    b.addEventListener('click',function(){applyFont(i);});
    box.appendChild(b);
  });
  syncFontList();
}
function applyFont(i){
  var f=FONTS[i];if(!f)return;
  document.documentElement.style.setProperty('--title-font',f.fam);
  try{localStorage.setItem('imm_font',String(i));}catch(e){}
  syncFontList();
}
function syncFontList(){
  var saved=localStorage.getItem('imm_font');
  var idx=(saved!==null&&FONTS[+saved])?+saved:0;
  document.querySelectorAll('#fontList .font-item').forEach(function(b,i){b.classList.toggle('on',i===idx);});
}
function initFont(){
  var saved=localStorage.getItem('imm_font');
  applyFont((saved!==null&&FONTS[+saved])?+saved:0);
}
var fontBtn=document.getElementById('fontBtn'),fontPop=document.getElementById('fontPop');
if(fontBtn)fontBtn.addEventListener('click',function(e){
  e.stopPropagation();
  engMenu.classList.remove('show');langMenu.classList.remove('show');if(palPop)palPop.classList.remove('show');
  fontPop.classList.toggle('show');
});
document.addEventListener('click',function(e){
  if(!e.target.closest('#fontBtn')&&!e.target.closest('#fontPop')){if(fontPop)fontPop.classList.remove('show');}
});
document.addEventListener('keydown',function(e){if(e.key==='Escape'&&fontPop)fontPop.classList.remove('show');});

function loadConfig(){
  return fetch('/api/config').then(function(r){return r.json();}).then(function(cfg){
    _CFG=cfg;
    var engs=cfg.models&&cfg.models.engines||{};
    ENGINES={};
    Object.keys(engs).forEach(function(k){ENGINES[k]=engs[k].display_name||k;});
    return cfg;
  }).catch(function(e){console.warn('[Init] config load failed:',e);return null;});
}

/* ---------- F11: 引擎菜单 + 参数默认值（来自后端配置） ---------- */
function initEngines(){
  var sel=document.getElementById('engineSelect');
  var menu=document.getElementById('engMenu');
  var keys=Object.keys(ENGINES);
  if(!keys.length||!sel)return;
  var cur=sel.value;
  sel.innerHTML='';
  if(menu)menu.innerHTML='';
  keys.forEach(function(k){
    var label=ENGINES[k];
    var o=document.createElement('option');o.value=k;o.textContent=label;sel.appendChild(o);
    if(menu){var b=document.createElement('button');b.className='ip-item';b.type='button';b.dataset.v=k;b.textContent=label;menu.appendChild(b);}
  });
  var def=_CFG&&_CFG.models&&_CFG.models.default_engine;
  if(ENGINES[cur])sel.value=cur;
  else if(def&&ENGINES[def])sel.value=def;
  else sel.value=keys[0];
  if(menu)menu.querySelectorAll('.ip-item').forEach(function(b){
    b.addEventListener('click',function(){
      menu.querySelectorAll('.ip-item').forEach(function(x){x.classList.remove('on');});
      b.classList.add('on');
      var es=document.getElementById('engineSelect');es.value=b.dataset.v;es.dispatchEvent(new Event('change'));
      closeMenus();
    });
  });
  syncEngMenu();
}
function syncEngMenu(){
  var cur=document.getElementById('engineSelect').value;
  document.querySelectorAll('#engMenu .ip-item').forEach(function(b){b.classList.toggle('on',b.dataset.v===cur);});
  syncChips();
}
function initDefaults(){
  if(!_CFG)return;
  var inf=_CFG.inference||{};
  function setv(id,v,def){var el=document.getElementById(id);if(el)el.value=(v!==undefined&&v!==null)?v:def;}
  setv('steps',inf.default_steps,8);
  setv('cfg',inf.default_cfg,1.0);
  setv('seed',inf.default_seed,-1);
  setv('batchSize',inf.default_batch_size,1);
  var ec=(_CFG.models&&_CFG.models.engines&&_CFG.models.engines[document.getElementById('engineSelect').value])||{};
  setv('width',ec.default_width||1024,1024);
  setv('height',ec.default_height||1024,1024);
}
function resetToDefaults(){
  if(!_CFG){window.alert('配置尚未加载，请稍后重试');return;}
  initDefaults();
  document.getElementById('seedvr2Toggle').checked=false;
  document.getElementById('esesToggle').checked=false;
  document.getElementById('vramToggle').checked=true;
  document.getElementById('vramGb').value=0.6;
  document.getElementById('upscaleSeed').value=-1;
  document.getElementById('vramSeed').value=-1;
  updateEst();
  window.alert('已恢复为后端默认参数');
}

/* ---------- F12: 最近生成（真实输出） ---------- */
function loadRecent(){
  var grid=document.getElementById('outGrid');
  if(!grid)return;
  grid.innerHTML='<p class="ph-note fs-11 pad-rec grid-span">加载最近生成…</p>';
  fetch('/api/outputs?page=1&page_size=9').then(function(r){return r.json();}).then(function(r){
    var list=r.outputs||[];
    if(!list.length){grid.innerHTML='<p class="ph-note fs-11 pad-rec grid-span">暂无生成记录</p>';return;}
    grid.innerHTML='';
    list.forEach(function(out,idx){
      var c=document.createElement('div');c.className='r-card';c.style.setProperty('--ar','1/1');
      var label=typeLabel(out.output_type)||'输出';
      var meta=engLabel(out.engine)+(out.created_at?' · '+String(out.created_at).substring(5,16):'');
      c.innerHTML='<div class="ph-img"><img src="/api/outputs/'+out.path+'" class="img-fit-md"><div class="r-actions"><button class="btn btn-sm" type="button" data-act="download">下载</button><button class="btn btn-sm" type="button" data-act="zip">ZIP</button><button class="btn btn-sm" type="button" data-act="redraw">重绘</button></div></div><div class="r-meta"><span class="r-type">'+escHtml(label)+'</span><b class="r-tt">'+escHtml((out.prompt||'生成结果').substring(0,18))+'</b><span class="r-sub">'+escHtml(meta)+'</span></div>';
      // P2-4 CSP 收紧：内联 onclick/onerror 改 data-act + 事件绑定；
      // 顺带消除 onclick 属性里 path/task_id 未经转义直接拼接的注入向量
      var hImg=c.querySelector('.ph-img img');
      if(hImg)hImg.onerror=function(){this.parentElement.textContent='加载失败';};
      var dlBtn=c.querySelector('button[data-act="download"]');
      if(dlBtn)dlBtn.addEventListener('click',function(ev){ev.stopPropagation();window.open('/api/outputs/'+out.path,'_blank');});
      var zipBtn=c.querySelector('button[data-act="zip"]');
      if(zipBtn)zipBtn.addEventListener('click',function(ev){ev.stopPropagation();window.open('/api/tasks/export?ids='+out.task_id,'_blank');});
      var rdBtn=c.querySelector('button[data-act="redraw"]');
      if(rdBtn)rdBtn.addEventListener('click',function(ev){ev.stopPropagation();redrawTask(out.task_id);});
      c.addEventListener('click',function(){openViewerReal(out,list,idx);});
      grid.appendChild(c);
    });
  }).catch(function(){grid.innerHTML='<p class="ph-note fs-11 pad-rec grid-span">加载失败</p>';});
}

/* ---------- F13: 队列悬浮球（真实任务） ---------- */
function renderQueue(){
  var box=document.getElementById('queueItems');if(!box)return;
  box.innerHTML='<p class="ph-note fs-10 pad-sm3">'+tr('loading')+'</p>';
  fetch('/api/tasks?page=1&page_size=30').then(function(r){return r.json();}).then(function(r){
    var list=(r.tasks||[]).filter(function(t){return t.status==='pending'||t.status==='processing'||t.status==='queued';});
    if(!list.length){box.innerHTML='<p class="ph-note fs-10 pad-sm3">'+tr('queue_idle')+'</p>';return;}
    box.innerHTML='';
    list.forEach(function(t){
      var d=document.createElement('div');d.className='q-item';
      var st=t.status==='processing'?tr('st_processing'):tr('st_pending');
      d.innerHTML='<div class="t"><b>'+escHtml((t.task_id||'').substring(0,12))+' · '+escHtml((t.prompt||tr('unnamed')).substring(0,16))+'</b><span>'+st+' · '+tr('out_count',{n:(t.output_count||0)})+'</span></div><span class="p">'+(t.status==='processing'?'…':'—')+'</span>';
      box.appendChild(d);
    });
  }).catch(function(){box.innerHTML='<p class="ph-note fs-10 pad-sm3">'+tr('load_failed')+'</p>';});
}
function loadQueueSummary(){
  fetch('/api/tasks?page=1&page_size=30').then(function(r){return r.json();}).then(function(r){
    var n=(r.tasks||[]).filter(function(t){return t.status==='pending'||t.status==='processing';}).length;
    if(qpText)qpText.textContent='队列 '+(n||0);
  }).catch(function(){});
}

/* ---------- 页面加载完成后的初始化（真实数据） ---------- */
renderPalette();
initAccent();
renderFontList();
initFont();
loadConfig().then(function(cfg){
  if(cfg)initEngines();
  if(cfg)initDefaults();
  updateEst();
  loadRecent();
  loadQueueSummary();
  loadHealth();
  setInterval(loadHealth,15000);
  setInterval(loadQueueSummary,5000);
  var he=document.getElementById('histEngine');
  if(he){he.innerHTML='<option value="">引擎</option>';Object.keys(ENGINES).forEach(function(k){var o=document.createElement('option');o.value=k;o.textContent=ENGINES[k];he.appendChild(o);});}
});
// 标记用户手动改过的参数（引擎切换时不再覆盖分辨率）
['width','height','steps','cfg','seed','batchSize'].forEach(function(id){var el=document.getElementById(id);if(el)el.addEventListener('input',function(){el.dataset.touched='1';});});


/* ── P1-1 首次使用协议确认（合规整改 2026-09-15）────────────── */
(function(){
  var KEY='image_mm:agreement:v1', VER='2026-09-15';
  try{
    if(localStorage.getItem(KEY)===VER) return;
    var box=document.getElementById('immAgreement'); if(!box) return;
    // P2-20：弹窗显示时收起所有抽屉/面板，避免同屏叠压
    closeRight();closeBottom();closeTop();closeHist();closeGalleryD();closeMenus();
    box.style.display='flex';
    var chk=document.getElementById('immAgreeChk'), btn=document.getElementById('immAgreeBtn');
    if(chk&&btn){ chk.addEventListener('change',function(){btn.disabled=!chk.checked;btn.style.opacity=chk.checked?'1':'.5';});
      btn.addEventListener('click',function(){ if(!chk.checked) return; try{localStorage.setItem(KEY,VER);}catch(e){} box.style.display='none'; }); }
  }catch(e){}
})();
