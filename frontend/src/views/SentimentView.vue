<template>
  <div class="sentiment-page">
    <PageHeader
      title="舆情监控"
      subtitle="基于 LLM 的股吧情绪分析"
    >
      <template #actions>
        <el-tooltip
          v-if="circuitBadge"
          :content="`guba 熔断器: ${circuitBadge.tooltip}`"
          placement="bottom"
        >
          <div
            class="circuit-badge"
            :class="`circuit-badge--${circuitBadge.level}`"
            @click="handleResetCircuit"
          >
            <span class="circuit-dot" />
            {{ circuitBadge.text }}
          </div>
        </el-tooltip>
        <el-dropdown
          trigger="click"
          @command="(c) => startBatchAnalyze(c)"
        >
          <el-button
            type="primary"
            :icon="Refresh"
            :loading="batchSubmitting || (batchProgress && batchProgress.running)"
          >
            批量分析
            <el-icon class="el-icon--right"><ArrowDownBold /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="monitored" :disabled="!monitoredCount">
                我的关注（{{ monitoredCount }}）
              </el-dropdown-item>
              <el-dropdown-item command="universe" :disabled="!universeCount">
                全部指数成分股（{{ universeCount }}）
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </template>
    </PageHeader>

    <!-- ── 顶部舆情状态总览（v7 2026-06-29）── -->
    <ModernCard class="overview-card" variant="glass">
      <div class="overview">
        <div class="overview__verdict">
          <span class="overview__verdict-label">今日舆情研判</span>
          <strong class="overview__verdict-text" :class="`verdict--${verdict.dir}`">
            {{ verdict.text }}
          </strong>
          <span v-if="verdict.detail" class="overview__verdict-detail">{{ verdict.detail }}</span>
        </div>
        <div class="overview__metrics">
          <div class="ov-metric">
            <span class="ov-metric__label">监控股今日产出</span>
            <strong>{{ coverage.scored_today || 0 }}<span class="ov-metric__total"> / {{ coverage.monitored_count || 0 }}</span></strong>
          </div>
          <div class="ov-metric">
            <span class="ov-metric__label">热门股池覆盖</span>
            <strong>{{ coverage.analyzed_top_picks || 0 }}<span class="ov-metric__total"> / {{ coverage.top_picks_count || 0 }}</span></strong>
          </div>
          <div class="ov-metric">
            <span class="ov-metric__label">因子覆盖</span>
            <strong>{{ coverage.indicators_today || 0 }}</strong>
          </div>
          <div class="ov-metric">
            <span class="ov-metric__label">极端信号</span>
            <strong>
              <span v-if="extremeCount" class="ov-extreme">{{ extremeCount }}</span>
              <span v-else class="ov-metric__muted">无</span>
            </strong>
          </div>
        </div>
        <div class="overview__jobs">
          <span
            v-for="job in healthJobs"
            :key="job.job_id"
            class="job-chip"
            :class="`job-chip--${jobLevel(job)}`"
            :title="jobTooltip(job)"
          >
            {{ jobShortName(job.job_id) }} · {{ jobLastStatus(job) }}
          </span>
        </div>
      </div>
      <!-- 告警条 -->
      <div v-if="circuitBadge || cookieStale" class="overview__alerts">
        <div v-if="circuitBadge" class="alert-chip alert-chip--circuit" :class="`alert-chip--${circuitBadge.level}`" @click="handleResetCircuit">
          <span class="alert-dot" /> {{ circuitBadge.text }}（点击重置）
        </div>
        <div v-if="cookieStale" class="alert-chip alert-chip--stale">
          帖子正文抓取临时降级：guba 触发速率型反爬，冷却后自动恢复；可运行 tools/guba_cookie_harvest.py 采集新 cookie 快速解锁（约 1 分钟生效，无需重启）
        </div>
      </div>
    </ModernCard>

    <!-- 批量分析进度条 -->
    <transition name="fade">
      <div v-if="batchProgress" class="batch-progress" :class="`batch-progress--${batchProgress.mode}`">
        <div class="batch-progress__head">
          <span class="batch-progress__title">
            <span v-if="batchProgress.running" class="batch-progress__pulse" />
            {{ batchProgress.mode === 'universe' ? '全部指数成分股' : '我的关注' }} 批量分析中
          </span>
          <span class="batch-progress__count">
            <strong>{{ batchProgress.completed + batchProgress.failed }}</strong>
            <span class="muted"> / {{ batchProgress.total }}</span>
            <span v-if="batchProgress.failed" class="warn">（失败 {{ batchProgress.failed }}）</span>
          </span>
        </div>
        <el-progress
          :percentage="batchProgress.total > 0
            ? Math.round((batchProgress.completed + batchProgress.failed) / batchProgress.total * 100)
            : 0"
          :status="batchProgress.running ? '' : 'success'"
          :stroke-width="10"
          :show-text="false"
        />
        <div class="batch-progress__detail">
          <span v-if="batchProgress.current" class="batch-progress__current">
            当前：<code>{{ batchProgress.current }}</code>
            <span v-if="batchProgress.currentName" class="batch-progress__name">
              {{ batchProgress.currentName }}
            </span>
            <span v-if="batchProgress.stuck" class="batch-progress__stuck" :title="'单只股票卡住超过 60 秒，后端将自动跳过'">
              已卡住
            </span>
          </span>
          <span v-else-if="!batchProgress.running" class="batch-progress__done">
            已完成，3 秒后自动收起
          </span>
        </div>
      </div>
    </transition>

    <el-tabs v-model="activeTab" class="sentiment-tabs">
      <!-- ── Tab 1：我的监控 ── -->
      <el-tab-pane label="我的监控" name="monitored">
        <div class="content-grid">
          <!-- 左侧：监控配置 -->
          <div class="left-panel">
            <ModernCard title="监控配置" description="添加需要监控情绪的股票">
              <div class="add-form">
                <el-select
                  v-model="selectedStock"
                  filterable
                  remote
                  reserve-keyword
                  :remote-method="searchStocks"
                  :loading="searching"
                  placeholder="输入代码或名称搜索"
                  value-key="code"
                  style="flex: 1"
                  clearable
                >
                  <el-option
                    v-for="s in searchResults"
                    :key="s.code"
                    :label="`${s.code}  ${s.name}`"
                    :value="s"
                  />
                </el-select>
                <el-button type="primary" @click="handleAdd" :disabled="!selectedStock">
                  添加
                </el-button>
              </div>

              <div class="config-list" :class="{ 'config-list--empty': !configs.length }">
                <div
                  v-for="cfg in configs"
                  :key="cfg.id"
                  class="config-item"
                >
                  <div class="config-item__info">
                    <span class="config-item__code">{{ cfg.stock_code }}</span>
                    <span class="config-item__name">{{ cfg.stock_name || '-' }}</span>
                  </div>
                  <el-button type="danger" link size="small" @click="handleDelete(cfg.id)">
                    删除
                  </el-button>
                </div>
                <EmptyHint
                  v-if="!configs.length"
                  icon="∅"
                  title="暂无监控股票"
                  description="上方搜索代码或名称，添加后点击批量分析"
                />
              </div>
            </ModernCard>
          </div>

          <!-- 右侧：情绪列表（手风琴） -->
          <div class="right-panel">
            <ModernCard title="最新情绪">
              <template #extra>
                <el-button text size="small" @click="fetchLatest">刷新</el-button>
              </template>
              <div v-loading="latestLoading">
                <div v-if="latest.length" class="sentiment-list">
                  <div
                    v-for="item in latest"
                    :key="item.stock_code"
                    class="sentiment-row"
                    :class="{ 'sentiment-row--active': expandedCode === item.stock_code }"
                  >
                    <!-- 摘要行（点击展开） -->
                    <div class="sentiment-summary" @click="toggleExpand(item.stock_code)">
                      <div class="sentiment-main">
                        <div class="sentiment-info">
                          <span class="stock-code">{{ item.stock_code }}</span>
                          <span class="stock-name">{{ item.stock_name || '-' }}</span>
                          <span
                            v-if="trendOf(item)"
                            class="trend-pill"
                            :class="`trend-pill--${trendOf(item).dir}`"
                            :title="`较上期 ${trendOf(item).delta > 0 ? '+' : ''}${trendOf(item).delta} 分`"
                          >{{ trendOf(item).icon }}</span>
                        </div>
                        <div class="sentiment-score-wrap">
                          <span
                            v-if="item.sentiment"
                            class="stance-pill"
                            :class="`stance-pill--${stanceKey(item.sentiment)}`"
                          >{{ item.sentiment }}</span>
                          <span v-else class="text-muted">-</span>
                          <span
                            v-if="item.score != null"
                            class="score-num"
                            :style="{ color: scoreColor(item.score) }"
                          >{{ item.score }}</span>
                          <el-icon
                            class="chevron"
                            :class="{ 'chevron--expanded': expandedCode === item.stock_code }"
                          ><ArrowDown /></el-icon>
                        </div>
                      </div>
                      <div
                        v-if="item.summary && item.summary !== '暂无数据'"
                        class="sentiment-desc"
                      >{{ item.summary }}</div>

                      <!-- 极端情绪 + 动量徽章 -->
                      <div
                        v-if="signalBadges(item).length"
                        class="signal-row"
                      >
                        <span
                          v-for="b in signalBadges(item)"
                          :key="b.type"
                          class="signal-badge"
                          :class="`signal-badge--${b.type}`"
                          :title="b.title"
                        >{{ b.icon }} {{ b.label }}</span>
                      </div>
                    </div>

                    <!-- 展开详情 -->
                    <Transition name="expand">
                      <div
                        v-if="expandedCode === item.stock_code"
                        class="sentiment-detail"
                      >
                        <div
                          v-if="isDashboardLoading(item.stock_code) && !dashboardOf(item.stock_code)"
                          class="dashboard-loading"
                        >
                          <span class="loading-dot" />
                          <span class="loading-dot" />
                          <span class="loading-dot" />
                          正在加载公司看板…
                        </div>
                        <StockDashboard
                          v-else-if="dashboardOf(item.stock_code)"
                          inline
                          :code="item.stock_code"
                          :name="item.stock_name"
                          :price="(dashboardOf(item.stock_code).financial || {}).price ?? item.score"
                          :total-market-cap="(dashboardOf(item.stock_code).financial || {}).total_market_cap"
                          :float-market-cap="(dashboardOf(item.stock_code).financial || {}).float_market_cap"
                          :ttm-pe="(dashboardOf(item.stock_code).financial || {}).ttm_pe"
                          :pe-percentile="(dashboardOf(item.stock_code).financial || {}).ttm_pe_percentile"
                          :pe-percentile-basis="(dashboardOf(item.stock_code).financial || {}).ttm_pe_percentile_basis"
                          :ttm-revenue="(dashboardOf(item.stock_code).financial || {}).ttm_revenue"
                          :ttm-net-profit="(dashboardOf(item.stock_code).financial || {}).ttm_net_profit"
                          :ttm-gross-profit="(dashboardOf(item.stock_code).financial || {}).ttm_gross_profit"
                          :quarters="(dashboardOf(item.stock_code).financial || {}).quarters"
                          :price-history="(dashboardOf(item.stock_code).financial || {}).price_history"
                          :pe-history="(dashboardOf(item.stock_code).financial || {}).pe_history"
                          :markers="sentimentMarkers(item.stock_code)"
                          marker-label="情绪分数"
                          :include="['header', 'valuation', 'kpi', 'price', 'quarterly']"
                        />

                        <div class="detail-grid">
                          <!-- 左：情绪趋势 -->
                          <div class="detail-col">
                            <div class="detail-col__head">
                              <span class="detail-col__title">情绪趋势</span>
                              <span v-if="historyOf(item.stock_code).length" class="detail-col__meta">
                                近 {{ historyOf(item.stock_code).length }} 天
                              </span>
                            </div>
                            <div v-loading="isHistoryLoading(item.stock_code)" class="history-list">
                              <EmptyHint
                                v-if="!historyOf(item.stock_code).length && !isHistoryLoading(item.stock_code)"
                                icon="∅"
                                title="暂无历史数据"
                                description="点击「立即分析」生成第一份报告"
                              />
                              <div
                                v-for="h in historyOf(item.stock_code).slice(0, 10)"
                                :key="h.date"
                                class="history-row"
                              >
                                <span class="h-date">{{ formatDate(h.date) }}</span>
                                <span
                                  class="stance-pill stance-pill--sm"
                                  :class="`stance-pill--${stanceKey(h.sentiment)}`"
                                >{{ h.sentiment }}</span>
                                <span
                                  class="h-score"
                                  :style="{ color: scoreColor(h.score) }"
                                >{{ h.score }}</span>
                                <span class="h-summary" :title="h.summary">{{ h.summary }}</span>
                              </div>
                            </div>
                          </div>

                          <!-- 右：相关帖子 -->
                          <div class="detail-col">
                            <div class="detail-col__head">
                              <span class="detail-col__title">相关帖子</span>
                              <span v-if="item.posts?.length" class="detail-col__meta">
                                {{ item.posts.length }} 条
                              </span>
                              <span
                                v-if="auditOf(item).mismatched > 0"
                                class="audit-pill audit-pill--warn"
                                :title="`${auditOf(item).mismatched} 条标题与实际页面不一致`"
                              >
                                {{ auditOf(item).mismatched }} 条不一致
                              </span>
                              <a
                                v-if="item.guba_url"
                                :href="item.guba_url"
                                target="_blank"
                                class="guba-link"
                                @click.stop
                              >打开股吧 →</a>
                            </div>
                            <div class="post-filter">
                              <el-checkbox v-model="onlyMismatch">只显示不一致</el-checkbox>
                              <el-button
                                v-if="item.posts?.length"
                                link
                                size="small"
                                :loading="rerunningCode === item.stock_code"
                                @click="handleRerunAudit(item)"
                              >重跑审计</el-button>
                            </div>
                            <div class="post-list">
                              <EmptyHint
                                v-if="!item.posts?.length"
                                icon="∅"
                                title="暂无帖子"
                                description="点击「立即分析」抓取最新讨论"
                              />
                              <div
                                v-for="(p, i) in filteredPosts(item)"
                                :key="p.post_id || i"
                                class="post-row"
                                :class="{ 'post-row--mismatch': auditStateOf(p) === 'mismatch' }"
                              >
                                <div class="post-row__main">
                                  <span
                                    class="audit-badge"
                                    :class="`audit-badge--${auditStateOf(p)}`"
                                    :title="auditTooltip(p)"
                                    @click.stop="togglePostDetail(p)"
                                  >{{ auditIcon(p) }}</span>
                                  <a
                                    href="#"
                                    class="post-title-link"
                                    :title="effectiveTitle(p)"
                                    @click.prevent.stop="openPostDialog(p, item)"
                                  >{{ effectiveTitle(p) }}</a>
                                </div>
                                <div
                                  v-if="expandedPostId === (p.post_id || `${item.stock_code}-${i}`)"
                                  class="post-diff"
                                >
                                  <div class="post-diff__line">
                                    <span class="post-diff__label">DB 标题：</span>
                                    <span class="post-diff__stored">{{ p.title }}</span>
                                  </div>
                                  <div
                                    v-if="p.actual_title && p.actual_title !== p.title"
                                    class="post-diff__line"
                                  >
                                    <span class="post-diff__label">实际标题：</span>
                                    <span class="post-diff__actual">{{ p.actual_title }}</span>
                                  </div>
                                  <div class="post-diff__actions">
                                    <el-button
                                      v-if="p.actual_title && p.actual_title !== p.title"
                                      size="small"
                                      type="primary"
                                      :loading="actingPostId === p.post_id"
                                      @click.stop="handleAccept(p)"
                                    >接受实际标题</el-button>
                                    <el-button
                                      size="small"
                                      type="danger"
                                      :loading="actingPostId === p.post_id"
                                      @click.stop="handleMarkBroken(p)"
                                    >标记为垃圾</el-button>
                                    <el-button
                                      v-if="p.audit_status && p.audit_status !== 'pending'"
                                      size="small"
                                      :loading="actingPostId === p.post_id"
                                      @click.stop="handleReset(p)"
                                    >重置审计</el-button>
                                    <el-button
                                      size="small"
                                      text
                                      @click.stop="expandedPostId = ''"
                                    >收起</el-button>
                                  </div>
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>

                        <!-- 操作栏 -->
                        <div class="detail-actions">
                          <el-button
                            size="small"
                            type="primary"
                            plain
                            :icon="Download"
                            :loading="fetchingFor === item.stock_code"
                            @click="handleFetchOnly(item)"
                          >仅拉取</el-button>
                          <el-button
                            size="small"
                            :icon="MagicStick"
                            :loading="analyzingFor === item.stock_code"
                            @click="handleAnalyzeOne(item)"
                          >立即分析</el-button>
                          <span class="action-hint">
                            「仅拉取」只更新帖子缓存，不调 LLM（快速验证网络）
                          </span>
                        </div>
                      </div>
                    </Transition>
                  </div>
                </div>
                <EmptyHint
                  v-else-if="!latestLoading"
                  icon="∅"
                  title="暂无情绪数据"
                  description="添加股票后点击批量分析"
                />
              </div>
            </ModernCard>
          </div>
        </div>
      </el-tab-pane>

      <!-- ── Tab 2：热门股池 ── -->
      <el-tab-pane label="热门股池" name="toppicks">
        <ModernCard
          title="今日热门股池"
          :description="topPicksScheduleDesc"
        >
          <template #extra>
            <el-button
              text
              size="small"
              :loading="topPicksAnalyzing"
              :disabled="!topPicks.length"
              @click="handleAnalyzeTopPicks"
            >分析 top20</el-button>
            <el-button
              text
              size="small"
              :loading="topPicksRefreshing"
              @click="handleRefreshTopPicks"
            >刷新+分析</el-button>
            <el-button text size="small" :loading="healthLoading" @click="fetchHealth">刷新状态</el-button>
          </template>
          <div v-loading="topPicksLoading" class="top-picks-list">
            <EmptyHint
              v-if="!topPicks.length && !topPicksLoading"
              icon="∅"
              title="暂无热门股数据"
              description="点击「刷新+分析」从新浪拉取最新成交额排名；工作日 16:05 自动刷新"
            />
            <div
              v-for="p in topPicks.slice(0, 20)"
              :key="p.stock_code"
              class="top-pick-row"
            >
              <span class="top-pick-rank">#{{ p.rank }}</span>
              <span class="top-pick-code">{{ p.stock_code }}</span>
              <span class="top-pick-name">{{ p.stock_name }}</span>
              <span
                v-if="p.is_monitored"
                class="top-pick-tag"
                title="已在监控中"
              >已监控</span>
              <span
                class="top-pick-sentiment"
                :class="p.score == null ? 'top-pick-sentiment--empty' : `top-pick-sentiment--${stanceKey(p.sentiment)}`"
                :title="p.sentiment_date ? `${p.sentiment_date} · ${p.summary || ''}` : '尚未生成情绪因子'"
              >
                {{ p.score == null ? '待分析' : `${p.sentiment || '-'} ${p.score}` }}
              </span>
            </div>
          </div>
        </ModernCard>

        <ModernCard
          v-if="extremeSignals.length"
          title="今日极端情绪"
          description="触发 2σ 极端阈值的监控股"
        >
          <div class="extreme-list">
            <div
              v-for="sig in extremeSignals.slice(0, 10)"
              :key="sig.stock_code"
              class="extreme-row"
            >
              <span class="extreme-code">{{ sig.stock_code }}</span>
              <span class="extreme-name">{{ sig.stock_name || '-' }}</span>
              <span class="extreme-score">{{ Number(sig.score).toFixed(0) }}</span>
              <span
                v-if="sig.panic_signal"
                class="signal-badge signal-badge--panic"
                title="非理性恐慌"
              >🔻 恐慌</span>
              <span
                v-if="sig.euphoria_signal"
                class="signal-badge signal-badge--euphoria"
                title="非理性狂热"
              >🔺 狂热</span>
              <span
                v-if="sig.momentum_cross"
                class="signal-badge signal-badge--momentum"
                title="EMA3 上穿 EMA5"
              >↗ 动量</span>
            </div>
          </div>
        </ModernCard>
      </el-tab-pane>

      <!-- ── Tab 3：全市场观测 ── -->
      <el-tab-pane label="全市场观测" name="universe">
        <IndexDashboard :date="dashboardDate" />
        <ModernCard title="指数成分股情绪" description="切换指数查看当日成分股情绪分布">
          <template #extra>
            <el-radio-group v-model="selectedIndexCode" size="small" class="index-filter">
              <el-radio-button label="">我的关注</el-radio-button>
              <el-radio-button
                v-for="idx in indices" :key="idx.code" :label="idx.code"
              >{{ idx.name }}</el-radio-button>
            </el-radio-group>
          </template>
          <div v-loading="universeLoading">
            <div v-if="universeList.length" class="sentiment-list">
              <div
                v-for="item in universeList"
                :key="item.stock_code"
                class="sentiment-row"
              >
                <div class="sentiment-summary">
                  <div class="sentiment-main">
                    <div class="sentiment-info">
                      <span class="stock-code">{{ item.stock_code }}</span>
                      <span class="stock-name">{{ item.stock_name || '-' }}</span>
                    </div>
                    <div class="sentiment-score-wrap">
                      <span
                        v-if="item.sentiment"
                        class="stance-pill"
                        :class="`stance-pill--${stanceKey(item.sentiment)}`"
                      >{{ item.sentiment }}</span>
                      <span v-else class="text-muted">-</span>
                      <span
                        v-if="item.score != null"
                        class="score-num"
                        :style="{ color: scoreColor(item.score) }"
                      >{{ item.score }}</span>
                    </div>
                  </div>
                  <div
                    v-if="signalBadges(item).length"
                    class="signal-row"
                  >
                    <span
                      v-for="b in signalBadges(item)"
                      :key="b.type"
                      class="signal-badge"
                      :class="`signal-badge--${b.type}`"
                      :title="b.title"
                    >{{ b.icon }} {{ b.label }}</span>
                  </div>
                </div>
              </div>
            </div>
            <EmptyHint
              v-else-if="!universeLoading"
              icon="∅"
              title="暂无成分股数据"
              description="切换指数或等待工作日 18:00 全市场爬取"
            />
          </div>
        </ModernCard>
      </el-tab-pane>
    </el-tabs>

    <!-- 帖子缓存查看器（v3, 2026-06-04）：guba 不可达时站内显示 -->
    <el-dialog
      v-model="postDialogOpen"
      :title="postDialogTitle"
      width="min(720px, 92vw)"
      :close-on-click-modal="false"
      class="post-dialog"
    >
      <div v-if="postDialogLoading" class="post-dialog__loading">加载中…</div>
      <div v-else-if="postDialogError" class="post-dialog__error">
        {{ postDialogError }}
      </div>
      <template v-else-if="postDialogPost">
        <div class="post-dialog__meta">
          <span class="audit-badge" :class="`audit-badge--${auditStateOf(postDialogPost)}`">
            {{ auditIcon(postDialogPost) }}
          </span>
          <span class="post-dialog__author">{{ postDialogPost.author || '匿名' }}</span>
          <span class="post-dialog__time">{{ postDialogPost.post_time || '-' }}</span>
        </div>
        <div
          v-if="postDialogPost.actual_title && postDialogPost.actual_title !== postDialogPost.title"
          class="post-dialog__title-diff"
        >
          <div><span class="post-dialog__label">DB 标题：</span>{{ postDialogPost.title }}</div>
          <div><span class="post-dialog__label">实际标题：</span>{{ postDialogPost.actual_title }}</div>
        </div>
        <div v-if="postDialogPost.content" class="post-dialog__body">
          {{ postDialogPost.content }}
        </div>
        <div v-else class="post-dialog__empty">
          <p>缓存中无正文（可能是抓取时 guba 不可达）。</p>
          <p class="post-dialog__hint">
            点击「重新抓取」让后端再尝试一次。如果熔断器是 open，会立刻返回 503。
          </p>
        </div>
        <div class="post-dialog__actions">
          <el-button
            type="primary"
            :loading="postRefreshing"
            @click="handleRefreshPostContent"
          >重新抓取正文</el-button>
          <el-button
            v-if="postDialogPost.url"
            link
            tag="a"
            :href="postDialogPost.url"
            target="_blank"
          >在 guba 打开</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, MagicStick, ArrowDown, Download, ArrowDownBold } from '@element-plus/icons-vue'
import {
  getSentimentConfigs, addSentimentConfig, deleteSentimentConfig,
  getSentimentLatest, getSentimentScores, analyzeSentiment,
  batchAnalyzeSentiment, getBatchAnalyzeStatus, getBatchAnalyzeCount,
  searchStocks as searchStocksApi,
  acceptPostActualTitle, markPostBroken, resetPostAudit,
  rerunSentimentAudit,
  fetchForumPostsOnly, getCircuitStatus, resetCircuit,
  getSentimentPost, refreshSentimentPostContent,
  getTopPicks, refreshTopPicks, analyzeTopPicks, getExtremeSignals,
  recomputeSentimentIndicators, getSentimentHealth, getTask,
  getStockDashboard,
} from '../api'
import {
  getUniverseIndices, getUniverseConstituents,
  getUniverseProgress, getUniverseCount, runUniverseCrawl,
} from '../api/universe'
import PageHeader from '../components/ui/PageHeader.vue'
import ModernCard from '../components/ui/ModernCard.vue'
import EmptyHint from '../components/ui/EmptyHint.vue'
import IndexDashboard from '../components/IndexDashboard.vue'
import StockDashboard from '../components/stock/StockDashboard.vue'

const configs = ref([])
const latest = ref([])
const historyByCode = ref({})          // code -> history[]
const historyLoadingFor = ref('')      // 当前正在加载历史的 code
const analyzingFor = ref('')           // 当前正在单只分析的 code
// v6 2026-06-15：dashboard 增强看板（按 code 缓存）
const dashboardByCode = ref({})        // code -> {financial, sentiment, ...}
const dashboardLoadingFor = ref('')    // 当前正在拉 dashboard 的 code
const selectedStock = ref(null)
const searchResults = ref([])
const searching = ref(false)
const expandedCode = ref('')           // 当前展开的行
const analyzing = ref(false)
const latestLoading = ref(false)
// v7 2026-06-29：tab 化 + 全市场观测用独立状态（避免与我的监控 latest 冲突）
const activeTab = ref('monitored')
const universeList = ref([])
const universeLoading = ref(false)
// ── 批量分析进度（v4, 2026-06-08）：监控列表 + 指数成分股双模式 ──
const batchProgress = ref(null)         // { mode, total, done, failed, current, running }
let batchPollTimer = null
const monitoredCount = ref(0)           // 「我的关注」范围股票数（按钮 label 用）
const universeCount = ref(0)            // 「全部指数成分股」范围股票数
const batchScope = ref(null)            // 'monitored' | 'universe' | null
const batchSubmitting = ref(false)      // 用户已点确认、等待后端 ack

async function loadBatchCounts() {
  try {
    const r = await getBatchAnalyzeCount()
    monitoredCount.value = r.data?.count ?? 0
  } catch { monitoredCount.value = 0 }
  try {
    const r = await getUniverseCount()
    universeCount.value = r.data?.count ?? 0
  } catch { universeCount.value = 0 }
}

function stopBatchPolling() {
  if (batchPollTimer) { clearInterval(batchPollTimer); batchPollTimer = null }
}

function startBatchPolling(mode) {
  stopBatchPolling()
  let lastCurrent = null
  let lastChangeAt = Date.now()
  let stuckWarned = false
  const tick = async () => {
    try {
      const r = mode === 'universe'
        ? await getUniverseProgress()
        : await getBatchAnalyzeStatus()
      const d = r.data || r
      // universe 模式：用 completed+failed 当 done；monitored 模式：直接读 done+failed
      const total = d.total ?? 0
      const completed = d.completed ?? d.done ?? 0
      const failed = d.failed ?? 0
      const running = !!d.running
      const current = d.current
        || d.by_index?.find?.((j) => j.status === 'running')?.index_code
        || null
      const currentName = d.current_name || ''
      // v5 2026-06-08：检测"卡住"信号——current 超过 60s 没变 → 标记 stuck
      if (current && current !== lastCurrent) {
        lastCurrent = current
        lastChangeAt = Date.now()
        stuckWarned = false
      }
      const stuck = running && current && (Date.now() - lastChangeAt) > 60_000
      batchProgress.value = { mode, total, completed, failed, running, current, currentName, stuck }
      if (stuck && !stuckWarned) {
        stuckWarned = true
        ElMessage.warning(`当前 ${current} ${currentName || ''} 已卡住超过 60 秒，后端将自动标记失败并继续。`)
      }
      if (!running) {
        // 任务结束：再轮询 1 次保险，然后停
        setTimeout(() => {
          stopBatchPolling()
          ElMessage.success(
            mode === 'universe'
              ? `全市场分析完成：成功 ${completed}，失败 ${failed}（共 ${total}）`
              : `批量分析完成：成功 ${completed}，失败 ${failed}（共 ${total}）`
          )
          // 3s 后收起进度条 + 刷新数据
          setTimeout(() => {
            batchProgress.value = null
            batchScope.value = null
            batchSubmitting.value = false
            // 触发下游刷新
            window.dispatchEvent(new CustomEvent('sentiment-batch-finished', { detail: { mode } }))
            fetchLatest()
            if (mode === 'universe') {
              window.dispatchEvent(new CustomEvent('sentiment-universe-finished'))
            }
          }, 3000)
        }, 1500)
      }
    } catch (e) {
      console.error('poll batch progress failed', e)
    }
  }
  tick()  // 立即跑一次
  batchPollTimer = setInterval(tick, 1500)
}

async function startBatchAnalyze(mode) {
  if (batchSubmitting.value || (batchProgress.value?.running)) {
    ElMessage.warning('已有批量分析任务在进行中')
    return
  }
  const count = mode === 'universe' ? universeCount.value : monitoredCount.value
  if (!count) {
    ElMessage.warning(mode === 'universe'
      ? '当前 universe 无成分股快照，请先 POST /api/sentiment/universe/refresh_constituents'
      : '请先添加监控股票')
    return
  }
  // 二次确认：把要分析的数量告诉用户
  const scopeLabel = mode === 'universe' ? '全部指数成分股' : '我的关注'
  try {
    await ElMessageBox.confirm(
      `将启动 ${scopeLabel} 的批量分析，共 ${count} 只股票。\n\n确定开始？`,
      '批量分析',
      { confirmButtonText: '开始', cancelButtonText: '取消', type: 'info' }
    )
  } catch { return }  // 用户取消

  batchScope.value = mode
  batchSubmitting.value = true
  batchProgress.value = { mode, total: count, completed: 0, failed: 0, running: true, current: '准备中...' }
  try {
    if (mode === 'universe') {
      await runUniverseCrawl('all', 5)
    } else {
      await batchAnalyzeSentiment()
    }
    ElMessage.info('已提交，开始轮询进度...')
    startBatchPolling(mode)
  } catch (e) {
    ElMessage.error('提交失败: ' + (e.response?.data?.message || e.message))
    batchProgress.value = null
    batchScope.value = null
    batchSubmitting.value = false
  }
}
// ── 审计相关状态 ──
const expandedPostId = ref('')         // 当前展开 diff 面板的 post_id
const actingPostId = ref('')           // 正在操作 accept/mark/reset 的 post_id
const rerunningCode = ref('')          // 正在重跑审计的 stock_code
const onlyMismatch = ref(false)        // 只显示不一致帖子
// ── 网络韧性相关状态（v2, 2026-06-04）──
const fetchingFor = ref('')            // 正在「仅拉取」的 stock_code
const circuitState = ref({             // guba 熔断器状态
  state: 'closed', failures: 0, cooldown_remaining: 0, cookie_stale: false,
})
// ── 帖子缓存查看器（v3, 2026-06-04）──
const postDialogOpen = ref(false)
const postDialogLoading = ref(false)
const postRefreshing = ref(false)
const postDialogPost = ref(null)
const postDialogError = ref('')
const postDialogTitle = computed(() => {
  const p = postDialogPost.value
  if (!p) return '帖子详情'
  return p.actual_title || p.title || '帖子详情'
})

// ── v3 升级（2026-06-06）：热门股池 + 极端情绪看板 ──
const topPicks = ref([])
const topPicksLoading = ref(false)
const topPicksRefreshing = ref(false)
const topPicksAnalyzing = ref(false)
const extremeSignals = ref([])
const extremeSignalsLoading = ref(false)
const health = ref(null)
const healthLoading = ref(false)

const dashboardDate = new Date().toISOString().slice(0, 10)

const coverage = computed(() => health.value?.coverage || {})
const healthJobs = computed(() => health.value?.jobs || [])

// v7 2026-06-29：顶部状态总览的研判结论
const extremeCount = computed(() => extremeSignals.value?.length || 0)
const verdict = computed(() => {
  const scored = latest.value.filter(it => it.score != null)
  if (!scored.length && !extremeCount.value) {
    return { dir: 'neutral', text: '暂无数据', detail: '尚无监控股产出情绪因子' }
  }
  const avg = scored.reduce((a, it) => a + Number(it.score), 0) / scored.length
  const panic = extremeSignals.value.filter(s => s.panic_signal).length
  const euph = extremeSignals.value.filter(s => s.euphoria_signal).length
  let dir = 'neutral', text = '情绪中性'
  if (avg >= 55 || euph > panic) { dir = 'bull'; text = '情绪偏多' }
  else if (avg <= 45 || panic > euph) { dir = 'bear'; text = '情绪偏空' }
  const detail = `监控股均分 ${avg.toFixed(1)}　恐慌 ${panic} · 狂热 ${euph}`
  return { dir, text, detail }
})
const topPicksJob = computed(() =>
  healthJobs.value.find(j => j.job_id === 'daily_top_picks') || null
)
const topPicksScheduleDesc = computed(() => {
  const job = topPicksJob.value
  if (!job) return '工作日 16:05 自动刷新成交额 top 100'
  const last = job.last_run?.finished_at || job.last_run?.started_at
  const next = job.next_run_time
  const parts = []
  parts.push(last ? `最近刷新：${last}` : '尚未运行')
  if (next) parts.push(`下次：${next}`)
  return parts.join('　·　')
})

// ── v4 指数筛选（2026-06-06）：在「全市场观测」tab 顶部加指数切换器 ──
const indices = ref([])                       // [{code, name, ...}]
const selectedIndexCode = ref('')             // '' = 我的关注（默认行为）
async function loadIndices() {
  try {
    const r = await getUniverseIndices()
    indices.value = r.data || r || []
  } catch { indices.value = [] }
}
async function loadUniverseConstituents(code) {
  if (!code) {
    universeList.value = []
    return
  }
  universeLoading.value = true
  try {
    const r = await getUniverseConstituents(code, {
      date: new Date().toISOString().slice(0, 10),
      limit: 500, offset: 0,
    })
    const list = r.data || r || []
    universeList.value = list.map(s => ({
      stock_code: s.stock_code,
      stock_name: s.stock_name,
      score: s.score,
      sentiment: s.sentiment,
      summary: '',
      posts: [],
      indicators: { ema3: s.ema3, ema5: s.ema5,
                     panic_signal: s.panic_signal,
                     euphoria_signal: s.euphoria_signal,
                     momentum_cross: s.momentum_cross },
      signals: { panic: s.panic_signal === 1,
                 euphoria: s.euphoria_signal === 1,
                 momentum_cross: s.momentum_cross === 1,
                 ema3: s.ema3, ema5: s.ema5 },
    }))
  } catch (e) {
    universeList.value = []
    ElMessage.error(e.response?.data?.error || '加载指数成分股失败')
  } finally { universeLoading.value = false }
}
watch(selectedIndexCode, (newCode) => {
  if (newCode) loadUniverseConstituents(newCode)
  else universeList.value = []
})

async function fetchTopPicks() {
  topPicksLoading.value = true
  try {
    const r = await getTopPicks()
    topPicks.value = r.data || r || []
  } catch { topPicks.value = [] }
  finally { topPicksLoading.value = false }
}

async function fetchHealth() {
  healthLoading.value = true
  try {
    const r = await getSentimentHealth()
    health.value = r.data || r || null
  } catch { health.value = null }
  finally { healthLoading.value = false }
}

async function waitTaskAndRefresh(taskId, successText) {
  if (!taskId) {
    setTimeout(() => { fetchTopPicks(); fetchHealth() }, 4000)
    return
  }
  for (let i = 0; i < 120; i++) {
    try {
      const r = await getTask(taskId)
      const task = r.data || r
      if (task.status === 'success') {
        ElMessage.success(successText)
        await Promise.all([fetchTopPicks(), fetchHealth(), fetchLatest(), fetchExtremeSignals()])
        return
      }
      if (task.status === 'failed') {
        ElMessage.error(task.error_message || '任务失败')
        await fetchHealth()
        return
      }
    } catch (e) {
      console.warn('poll top picks task failed', e)
    }
    await new Promise(resolve => setTimeout(resolve, 1500))
  }
  ElMessage.warning('任务仍在运行，请稍后查看任务中心')
  await Promise.all([fetchTopPicks(), fetchHealth()])
}

async function handleRefreshTopPicks() {
  topPicksRefreshing.value = true
  try {
    const r = await refreshTopPicks(100, false, 20)
    const taskId = (r.data || r).task_id
    ElMessage.info('已提交热门股池刷新与 top20 情绪分析')
    await waitTaskAndRefresh(taskId, '热门股池刷新与分析完成')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '刷新失败')
  } finally { topPicksRefreshing.value = false }
}

async function handleAnalyzeTopPicks() {
  topPicksAnalyzing.value = true
  try {
    const r = await analyzeTopPicks(20)
    const taskId = (r.data || r).task_id
    ElMessage.info('已提交热门股 top20 情绪分析')
    await waitTaskAndRefresh(taskId, '热门股 top20 分析完成')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '提交失败')
  } finally { topPicksAnalyzing.value = false }
}

async function fetchExtremeSignals() {
  extremeSignalsLoading.value = true
  try {
    const r = await getExtremeSignals()
    extremeSignals.value = r.data || r || []
  } catch { extremeSignals.value = [] }
  finally { extremeSignalsLoading.value = false }
}

// 极端情绪徽章
function signalBadges(item) {
  const badges = []
  const sig = item.signals || {}
  const ind = item.indicators || {}
  if (sig.panic || ind.panic_signal === 1) {
    badges.push({ type: 'panic', icon: '🔻', label: '恐慌', title: '非理性恐慌爆发（看空 > 30日均值+2σ）' })
  }
  if (sig.euphoria || ind.euphoria_signal === 1) {
    badges.push({ type: 'euphoria', icon: '🔺', label: '狂热', title: '非理性狂热爆发（看多 > 30日均值+2σ）' })
  }
  if (sig.momentum_cross || ind.momentum_cross === 1) {
    badges.push({ type: 'momentum', icon: '↗', label: '动量', title: 'EMA3 上穿 EMA5' })
  }
  return badges
}

function stanceKey(s) {
  if (s === '乐观') return 'bull'
  if (s === '悲观') return 'bear'
  return 'neutral'
}
function scoreColor(s) {
  if (s >= 60) return 'var(--color-up)'
  if (s >= 40) return 'var(--color-warning)'
  return 'var(--color-success)'
}
function jobShortName(jobId) {
  const names = {
    daily_sentiment: '每日情绪',
    daily_top_picks: '热点股',
    daily_indicators_recompute: '因子重算',
    forum_prefetch: '帖子预拉',
  }
  return names[jobId] || jobId
}
function jobLastStatus(job) {
  const status = job.last_run?.status
  if (status === 'success') return '成功'
  if (status === 'failed') return '失败'
  if (status === 'skipped') return '跳过'
  if (!job.enabled) return '暂停'
  return '未运行'
}
function jobLevel(job) {
  if (!job.enabled) return 'muted'
  const status = job.last_run?.status
  if (status === 'failed') return 'danger'
  if (status === 'success') return 'ok'
  if (status === 'skipped') return 'warn'
  return 'idle'
}
function jobTooltip(job) {
  const run = job.last_run
  const last = run?.finished_at || run?.started_at || '暂无运行记录'
  const next = job.next_run_time || '暂无下次时间'
  return `${job.name}\n最近：${last}\n下次：${next}${run?.message ? `\n${run.message}` : ''}`
}
function formatDate(d) {
  if (!d) return ''
  return d.length > 10 ? d.slice(5) : d
}
// 计算较上期趋势：item 内有 score/无 prev 时返回 null
function trendOf(item) {
  if (item.score == null) return null
  const hist = historyByCode.value[item.stock_code]
  if (!hist || hist.length < 2) return null
  const prev = hist[1]?.score
  if (prev == null) return null
  const delta = item.score - prev
  if (delta > 0) return { dir: 'up', icon: '▲', delta }
  if (delta < 0) return { dir: 'down', icon: '▼', delta }
  return { dir: 'flat', icon: '-', delta }
}
function historyOf(code) {
  return historyByCode.value[code] || []
}
function isHistoryLoading(code) {
  return historyLoadingFor.value === code
}
function dashboardOf(code) {
  return dashboardByCode.value[code] || null
}
function isDashboardLoading(code) {
  return dashboardLoadingFor.value === code
}

// 把 sentiment history 序列化成 PriceTrendChart 的 markers
// - panic / euphoria / momentum_cross → extreme（markPoint ✱）
// - 其他有 score 的日期 → normal（scatter）
function sentimentMarkers(code) {
  const hist = historyByCode.value[code] || []
  const markers = []
  for (const h of hist) {
    if (h.score == null || !h.date) continue
    const sig = h.signals || {}
    if (sig.panic_signal) {
      markers.push({
        date: h.date, value: h.score, kind: 'extreme',
        label: `🔻 ${h.score}`, color: '#e11d48',
      })
    } else if (sig.euphoria_signal) {
      markers.push({
        date: h.date, value: h.score, kind: 'extreme',
        label: `🔺 ${h.score}`, color: '#f59e0b',
      })
    } else if (sig.momentum_cross) {
      markers.push({
        date: h.date, value: h.score, kind: 'extreme',
        label: `↗ ${h.score}`, color: '#10b981',
      })
    } else {
      // 普通日：按 sentiment 给色
      const color = h.sentiment === '乐观' ? '#f97316'
        : h.sentiment === '悲观' ? '#2563eb'
        : '#94a3b8'
      markers.push({
        date: h.date, value: h.score, kind: 'normal', color,
      })
    }
  }
  return markers
}

// ── 审计相关函数 ──
function auditStateOf(p) {
  if (!p) return 'pending'
  if (p.audit_status === 'broken') return 'broken'
  if (p.audit_status === 'manual_accepted') return 'verified'
  if (p.audit_status === 'mismatch' || p.title_match === 0) return 'mismatch'
  if (p.audit_status === 'verified' || p.title_match === 1) return 'verified'
  return 'pending'
}
function auditIcon(p) {
  const s = auditStateOf(p)
  if (s === 'verified') return '✓'
  if (s === 'mismatch') return '⚠'
  if (s === 'broken') return '🚫'
  return '?'
}
function auditTooltip(p) {
  const s = auditStateOf(p)
  if (s === 'verified') return '标题与实际页面一致'
  if (s === 'mismatch') return '标题与实际页面不一致，点击查看 diff'
  if (s === 'broken') return '已标记为垃圾'
  return '尚未审计'
}
function effectiveTitle(p) {
  if (!p) return ''
  if (auditStateOf(p) === 'mismatch' && p.actual_title) return p.actual_title
  return p.title || ''
}
function auditOf(item) {
  const posts = item.posts || []
  let matched = 0, mismatched = 0, pending = 0, broken = 0
  for (const p of posts) {
    const s = auditStateOf(p)
    if (s === 'verified') matched++
    else if (s === 'mismatch') mismatched++
    else if (s === 'broken') broken++
    else pending++
  }
  return { matched, mismatched, pending, broken, total: posts.length }
}
function filteredPosts(item) {
  const posts = item.posts || []
  if (!onlyMismatch.value) return posts
  return posts.filter(p => auditStateOf(p) === 'mismatch')
}
function togglePostDetail(p) {
  const id = p.post_id || ''
  if (expandedPostId.value === id) {
    expandedPostId.value = ''
    return
  }
  expandedPostId.value = id
}

async function handleRerunAudit(item) {
  rerunningCode.value = item.stock_code
  try {
    await rerunSentimentAudit(item.stock_code, { reset: false })
    ElMessage.success(`已启动重跑审计 (${item.stock_code})`)
    setTimeout(fetchLatest, 4000)
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '重跑失败')
  } finally {
    rerunningCode.value = ''
  }
}

async function handleAccept(p) {
  if (!p.post_id) {
    ElMessage.warning('缺少 post_id，无法操作')
    return
  }
  actingPostId.value = p.post_id
  try {
    await acceptPostActualTitle(p.post_id)
    ElMessage.success('已接受实际标题')
    expandedPostId.value = ''
    await fetchLatest()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '操作失败')
  } finally {
    actingPostId.value = ''
  }
}

async function handleMarkBroken(p) {
  if (!p.post_id) {
    ElMessage.warning('缺少 post_id，无法操作')
    return
  }
  actingPostId.value = p.post_id
  try {
    await markPostBroken(p.post_id)
    ElMessage.success('已标记为垃圾')
    expandedPostId.value = ''
    await fetchLatest()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '操作失败')
  } finally {
    actingPostId.value = ''
  }
}

async function handleReset(p) {
  if (!p.post_id) return
  actingPostId.value = p.post_id
  try {
    await resetPostAudit(p.post_id)
    ElMessage.success('已重置审计')
    await fetchLatest()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '操作失败')
  } finally {
    actingPostId.value = ''
  }
}

async function searchStocks(q) {
  if (!q || q.length < 2) { searchResults.value = []; return }
  searching.value = true
  try {
    const { data } = await searchStocksApi(q)
    searchResults.value = data || []
  } catch { searchResults.value = [] }
  finally { searching.value = false }
}

async function fetchConfigs() {
  try {
    const { data } = await getSentimentConfigs()
    configs.value = data || []
  } catch { /* noop */ }
}

async function fetchLatest() {
  latestLoading.value = true
  try {
    const { data } = await getSentimentLatest()
    latest.value = data || []
  } catch { /* noop */ }
  finally { latestLoading.value = false }
}

async function loadHistory(code) {
  if (historyByCode.value[code]) return      // 已缓存则跳过
  historyLoadingFor.value = code
  try {
    const { data } = await getSentimentScores(code, 30)
    historyByCode.value = { ...historyByCode.value, [code]: data || [] }
  } catch { /* noop */ }
  finally { historyLoadingFor.value = '' }
}

async function loadDashboard(code) {
  if (dashboardByCode.value[code] || dashboardLoadingFor.value === code) return
  dashboardLoadingFor.value = code
  try {
    const { data } = await getStockDashboard(code, { days: 60, sentiment: 0 })
    dashboardByCode.value = { ...dashboardByCode.value, [code]: data || {} }
  } catch (e) {
    // 单只拉取失败不影响主流程
    console.warn('dashboard load failed', code, e)
  } finally { dashboardLoadingFor.value = '' }
}

async function toggleExpand(code) {
  if (expandedCode.value === code) {
    expandedCode.value = ''
    return
  }
  expandedCode.value = code
  await Promise.all([loadHistory(code), loadDashboard(code)])
}

async function handleAdd() {
  if (!selectedStock.value) return
  const { code, name } = selectedStock.value
  try {
    await addSentimentConfig(code, name)
    ElMessage.success(`已添加 ${code} ${name}`)
    selectedStock.value = null
    searchResults.value = []
    fetchConfigs()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '添加失败')
  }
}

async function handleDelete(id) {
  try {
    await deleteSentimentConfig(id)
    ElMessage.success('已删除')
    fetchConfigs()
  } catch { ElMessage.error('删除失败') }
}

async function handleBatchAnalyze() {
  // 旧版入口已废弃：现在通过页头的「批量分析」下拉按钮触发，支持我的关注 / 全部成分股双模式 + 实时进度
  // 保留该函数仅为避免外部引用报错
  ElMessage.info('请使用页头的「批量分析」下拉按钮')
  return
}

async function handleAnalyzeOne(item) {
  analyzingFor.value = item.stock_code
  try {
    await analyzeSentiment(item.stock_code, item.forum_type || 'eastmoney')
    // 清缓存并重新拉
    delete historyByCode.value[item.stock_code]
    await Promise.all([fetchLatest(), loadHistory(item.stock_code)])
    ElMessage.success(`${item.stock_code} 分析完成`)
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '分析失败')
  } finally { analyzingFor.value = '' }
}

// ── 网络韧性：仅拉取 + 熔断器（v2, 2026-06-04） ──────────────────────
const circuitBadge = computed(() => {
  const s = circuitState.value
  if (s.state === 'open') {
    const sec = Math.ceil(s.cooldown_remaining)
    return {
      level: 'danger',
      text: `guba 熔断 ${sec}s`,
      tooltip: `连续 ${s.failures} 次失败，${sec} 秒后重试`,
    }
  }
  if (s.state === 'half_open') {
    return { level: 'warning', text: 'guba 探测中', tooltip: '正在探测' }
  }
  if (s.state === 'closed' && s.failures > 0) {
    return {
      level: 'warning',
      text: `guba 异常 ${s.failures}`,
      tooltip: `已记录 ${s.failures} 次失败，未达熔断阈值`,
    }
  }
  return null
})

async function fetchCircuit() {
  try {
    const r = await getCircuitStatus()
    circuitState.value = r.data || r
  } catch { /* 静默失败 */ }
}

const cookieStale = computed(() => !!circuitState.value?.cookie_stale)

async function handleFetchOnly(item) {
  const code = item.stock_code
  fetchingFor.value = code
  try {
    const r = await fetchForumPostsOnly(code, { days: 3, fetch_content: true, audit: true })
    const d = r.data || r
    const audit = d.audit || {}
    const mismatch = audit.mismatched || 0
    ElMessage.success(
      `${code} 已拉取 ${d.posts_count} 条帖子` +
      (mismatch > 0 ? `，${mismatch} 条标题不一致` : '')
    )
    // 更新熔断器状态
    if (d.circuit_state) circuitState.value = d.circuit_state
    // 刷新帖子列表
    await fetchLatest()
  } catch (e) {
    const status = e.response?.status
    const data = e.response?.data
    if (status === 503 && data?.circuit_state) {
      circuitState.value = data.circuit_state
      ElMessage.warning(
        `guba 暂时不可达，已熔断 ${Math.ceil(data.circuit_state.cooldown_remaining || 0)} 秒`
      )
    } else {
      ElMessage.error(data?.error || '拉取失败')
    }
  } finally { fetchingFor.value = '' }
}

async function handleResetCircuit() {
  try {
    const r = await resetCircuit()
    circuitState.value = (r.data || r).circuit_state
    ElMessage.success('熔断器已重置')
  } catch { ElMessage.error('重置失败') }
}

// ── 帖子缓存查看器：guba 不可达时站内显示 ──
async function openPostDialog(p, item) {
  postDialogOpen.value = true
  postDialogLoading.value = true
  postDialogError.value = ''
  postDialogPost.value = {
    // 先用列表里的浅数据撑住 UI
    id: p.post_id,
    title: p.title,
    actual_title: p.actual_title,
    audit_status: p.audit_status,
    title_match: p.title_match,
    url: p.url,
    author: '',
    post_time: '',
    content: '',
    stock_code: item?.stock_code || '',
  }
  if (!p.post_id) {
    postDialogLoading.value = false
    return
  }
  try {
    const r = await getSentimentPost(p.post_id)
    postDialogPost.value = r.data || r
  } catch (e) {
    postDialogError.value = e.response?.data?.error || '加载帖子失败'
  } finally {
    postDialogLoading.value = false
  }
}

async function handleRefreshPostContent() {
  const p = postDialogPost.value
  if (!p?.id) return
  postRefreshing.value = true
  try {
    const r = await refreshSentimentPostContent(p.id)
    const d = r.data || r
    postDialogPost.value = d.post || p
    if (d.circuit_state) circuitState.value = d.circuit_state
    if (d.post?.content) {
      ElMessage.success('已抓取最新正文')
    } else if (d.fetch_error) {
      ElMessage.warning(`抓取完成但无正文：${d.fetch_error}`)
    } else {
      ElMessage.info('抓取完成')
    }
  } catch (e) {
    const status = e.response?.status
    const data = e.response?.data
    if (status === 503 && data?.circuit_state) {
      circuitState.value = data.circuit_state
      ElMessage.warning(
        `guba 暂时不可达，已熔断 ${Math.ceil(data.circuit_state.cooldown_remaining || 0)} 秒`
      )
    } else {
      ElMessage.error(data?.error || '抓取失败')
    }
  } finally {
    postRefreshing.value = false
  }
}

onMounted(() => {
  fetchConfigs()
  fetchLatest()
  fetchCircuit()
  fetchTopPicks()
  fetchExtremeSignals()
  fetchHealth()
  loadIndices()
  loadBatchCounts()
})
onUnmounted(() => stopBatchPolling())
</script>

<style scoped>
.sentiment-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.content-grid {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: var(--space-4);
  align-items: start;
}
.left-panel,
.right-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-width: 0;
}

.pipeline-card :deep(.modern-card__extra) {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}
.pipeline-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-3);
}
.pipeline-metric {
  min-width: 0;
  padding: var(--space-4);
  border: 1px solid rgba(228, 228, 231, 0.72);
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, rgba(250, 250, 250, 0.92), rgba(245, 247, 255, 0.62));
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: all var(--duration-page) var(--ease);
}
.pipeline-metric:hover {
  transform: translateY(-1px);
  border-color: rgba(99, 102, 241, 0.22);
  box-shadow: var(--shadow-sm);
}
.pipeline-metric--wide {
  grid-column: span 1;
}
.pipeline-metric__label {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-weight: var(--weight-medium);
}
.pipeline-metric strong {
  font-size: 24px;
  line-height: 1;
  letter-spacing: -0.03em;
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
}
.pipeline-metric span:last-child {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}
.job-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.job-chip {
  display: inline-flex;
  align-items: center;
  padding: 3px 8px;
  border-radius: 999px;
  border: 1px solid transparent;
  font-size: 11px;
  font-weight: var(--weight-medium);
  white-space: nowrap;
}
.job-chip--ok {
  background: var(--color-success-soft);
  color: var(--color-success);
  border-color: rgba(4, 120, 87, 0.22);
}
.job-chip--danger {
  background: var(--color-danger-soft);
  color: var(--color-danger);
  border-color: rgba(220, 38, 38, 0.22);
}
.job-chip--warn {
  background: rgba(245, 158, 11, 0.10);
  color: var(--color-warning);
  border-color: rgba(245, 158, 11, 0.22);
}
.job-chip--muted,
.job-chip--idle {
  background: var(--color-bg-muted);
  color: var(--color-text-tertiary);
  border-color: var(--color-divider);
}

.add-form {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}

/* ── 网络韧性：guba 熔断器徽章（v2, 2026-06-04）── */
.circuit-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: var(--text-xs, 12px);
  font-weight: var(--weight-medium, 500);
  cursor: pointer;
  transition: all 0.18s ease;
  user-select: none;
  backdrop-filter: blur(8px);
  border: 1px solid transparent;
}
.circuit-badge:hover { transform: translateY(-1px); }
.circuit-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}
.circuit-badge--warning {
  background: rgba(245, 158, 11, 0.12);
  color: var(--color-warning, #f59e0b);
  border-color: rgba(245, 158, 11, 0.25);
}
.circuit-badge--warning .circuit-dot {
  background: var(--color-warning, #f59e0b);
  box-shadow: 0 0 6px rgba(245, 158, 11, 0.6);
}
.circuit-badge--danger {
  background: rgba(239, 68, 68, 0.12);
  color: var(--color-danger);
  border-color: rgba(239, 68, 68, 0.25);
  animation: pulse-danger 1.6s ease-in-out infinite;
}
.circuit-badge--danger .circuit-dot {
  background: var(--color-danger);
  box-shadow: 0 0 8px rgba(239, 68, 68, 0.7);
}
@keyframes pulse-danger {
  0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
  50% { box-shadow: 0 0 0 4px rgba(239, 68, 68, 0); }
}
.add-form :deep(.el-select) {
  flex: 1;
  min-width: 0;
}
.config-list {
  display: flex;
  flex-direction: column;
}
.config-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--color-divider);
}
.config-item:last-child { border-bottom: none; }
.config-item__info {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.config-item__code {
  font-family: var(--font-mono);
  font-weight: var(--weight-semibold);
  font-size: var(--text-sm);
  color: var(--color-text-primary);
}
.config-item__name {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.hint-text {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  margin-right: var(--space-2);
}

/* ── 情绪列表（手风琴） ── */
.sentiment-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.sentiment-row {
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  background: var(--color-bg-elevated);
  overflow: hidden;
  transition: all var(--duration-fast) var(--ease);
}
.sentiment-row:hover {
  border-color: var(--color-border-strong);
}
.sentiment-row--active {
  border-color: var(--color-accent);
  box-shadow: var(--shadow-md);
}
.sentiment-summary {
  padding: var(--space-3) var(--space-4);
  cursor: pointer;
}
.sentiment-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}
.sentiment-info {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}
.stock-code {
  font-family: var(--font-mono);
  font-weight: var(--weight-semibold);
  font-size: var(--text-sm);
  color: var(--color-text-primary);
}
.stock-name {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}
.sentiment-score-wrap {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}
.score-num {
  font-weight: var(--weight-semibold);
  font-size: var(--text-md);
  font-variant-numeric: tabular-nums;
  min-width: 24px;
  text-align: right;
}
.sentiment-desc {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin-top: var(--space-2);
  line-height: var(--leading-relaxed);
}

/* 趋势小标签（▲▼—） */
.trend-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: var(--weight-semibold);
}
.trend-pill--up {
  background: var(--color-up-soft);
  color: var(--color-up);
}
.trend-pill--down {
  background: var(--color-down-soft);
  color: var(--color-down);
}
.trend-pill--flat {
  background: var(--color-bg-muted);
  color: var(--color-text-tertiary);
}

/* 雪佛龙图标 */
.chevron {
  color: var(--color-text-tertiary);
  transition: transform var(--duration-base) var(--ease);
  margin-left: var(--space-1);
}
.chevron--expanded {
  transform: rotate(180deg);
  color: var(--color-accent);
}

/* ── 立场胶囊 ── */
.stance-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
}
.stance-pill--sm {
  padding: 1px 7px;
  font-size: 11px;
}
.stance-pill--bull {
  background: var(--color-up-soft);
  color: var(--color-up);
}
.stance-pill--bear {
  background: var(--color-down-soft);
  color: var(--color-down);
}
.stance-pill--neutral {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

/* ── 展开详情 ── */
.sentiment-detail {
  border-top: 1px solid var(--color-divider);
  background: var(--color-bg-subtle);
  padding: var(--space-4);
}
.dashboard-loading {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-elevated);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-4);
}
.dashboard-loading .loading-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-accent);
  animation: dot-bounce 1.2s infinite ease-in-out both;
}
.dashboard-loading .loading-dot:nth-child(1) { animation-delay: -0.32s; }
.dashboard-loading .loading-dot:nth-child(2) { animation-delay: -0.16s; }
@keyframes dot-bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
}
.detail-col {
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.detail-col__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--color-divider);
}
.detail-col__title {
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  letter-spacing: -0.01em;
}
.detail-col__meta {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-variant-numeric: tabular-nums;
}
.detail-col__head .guba-link {
  margin-left: auto;
}

/* ── 历史行 ── */
.history-list,
.post-list {
  display: flex;
  flex-direction: column;
  min-height: 60px;
}
.history-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--color-divider);
  font-size: var(--text-sm);
}
.history-row:last-child { border-bottom: none; }
.h-date {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  min-width: 50px;
  flex-shrink: 0;
}
.h-score {
  font-weight: var(--weight-semibold);
  font-size: var(--text-sm);
  min-width: 28px;
  text-align: right;
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}
.h-summary {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: var(--leading-normal);
}

.guba-link {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  text-decoration: none;
  transition: color var(--duration-fast) var(--ease);
}
.guba-link:hover { color: var(--color-accent); }

.post-title-text {
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

/* ── 操作栏 ── */
.detail-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px dashed var(--color-border);
}
.action-hint {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

/* ── 审计相关样式（v1, 2026-06-04） ── */
.audit-pill {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border-radius: var(--radius-full);
  font-size: 11px;
  font-weight: var(--weight-medium);
  margin-left: var(--space-2);
}
.audit-pill--warn {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.post-filter {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.post-row {
  display: block;
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--color-divider);
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  line-height: var(--leading-normal);
}
.post-row:last-child { border-bottom: none; }
.post-row--mismatch {
  background: linear-gradient(to right, var(--color-warning-soft) 0, transparent 60%);
  border-radius: var(--radius-sm);
  padding-left: var(--space-2);
  padding-right: var(--space-2);
}
.post-row__main {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
}

.audit-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  font-size: 11px;
  font-weight: var(--weight-semibold);
  cursor: pointer;
  margin-top: 1px;
  transition: transform var(--duration-fast) var(--ease);
}
.audit-badge:hover {
  transform: scale(1.15);
}
.audit-badge--verified {
  background: var(--color-down-soft);
  color: var(--color-down);
}
.audit-badge--mismatch {
  background: var(--color-warning-soft);
  color: var(--color-warning);
  animation: pulse-warn 2s ease-in-out infinite;
}
.audit-badge--pending {
  background: var(--color-bg-muted);
  color: var(--color-text-tertiary);
}
.audit-badge--broken {
  background: var(--color-up-soft);
  color: var(--color-up);
  text-decoration: line-through;
}
@keyframes pulse-warn {
  0%, 100% { box-shadow: 0 0 0 0 var(--color-warning-soft); }
  50% { box-shadow: 0 0 0 3px transparent; }
}

.post-title-link {
  flex: 1;
  min-width: 0;
  color: var(--color-text-primary);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  transition: color var(--duration-fast) var(--ease);
}
.post-title-link:hover {
  color: var(--color-accent);
}

/* diff 面板 */
.post-diff {
  margin-top: var(--space-2);
  padding: var(--space-3);
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
}
.post-diff__line {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-1);
  align-items: flex-start;
}
.post-diff__line:last-of-type {
  margin-bottom: var(--space-2);
}
.post-diff__label {
  flex-shrink: 0;
  color: var(--color-text-tertiary);
  font-weight: var(--weight-medium);
  min-width: 60px;
}
.post-diff__stored {
  color: var(--color-text-secondary);
  text-decoration: line-through;
  text-decoration-color: var(--color-up);
  word-break: break-all;
}
.post-diff__actual {
  color: var(--color-down);
  font-weight: var(--weight-medium);
  word-break: break-all;
}
.post-diff__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px dashed var(--color-border);
}

/* ── 展开过渡 ── */
.expand-enter-active,
.expand-leave-active {
  transition: opacity var(--duration-base) var(--ease),
              max-height var(--duration-slow) var(--ease);
  overflow: hidden;
}
.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
}
.expand-enter-to,
.expand-leave-from {
  opacity: 1;
  max-height: 1200px;
}

.text-muted { color: var(--color-text-tertiary); }

@media (max-width: 1100px) {
  .content-grid {
    grid-template-columns: 1fr;
  }
  .detail-grid {
    grid-template-columns: 1fr;
  }
  .pipeline-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .pipeline-grid {
    grid-template-columns: 1fr;
  }
}

/* ── v3 极端情绪徽章（2026-06-06）── */
.signal-row {
  display: flex;
  gap: 6px;
  margin-top: var(--space-2);
  flex-wrap: wrap;
}
.signal-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: var(--weight-medium);
  cursor: help;
}
.signal-badge--panic {
  background: rgba(239, 68, 68, 0.12);
  color: var(--color-danger);
  border: 1px solid rgba(239, 68, 68, 0.3);
}
.signal-badge--euphoria {
  background: rgba(245, 158, 11, 0.12);
  color: var(--color-warning, #f59e0b);
  border: 1px solid rgba(245, 158, 11, 0.3);
}
.signal-badge--momentum {
  background: rgba(16, 185, 129, 0.12);
  color: var(--color-up, #10b981);
  border: 1px solid rgba(16, 185, 129, 0.3);
}

/* ── v3 极端情绪看板 ── */
.extreme-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.extreme-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--color-divider);
  font-size: var(--text-sm);
}
.extreme-row:last-child { border-bottom: none; }
.extreme-code {
  font-family: var(--font-mono);
  font-weight: var(--weight-semibold);
  min-width: 56px;
}
.extreme-name {
  color: var(--color-text-secondary);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.extreme-score {
  font-weight: var(--weight-semibold);
  font-variant-numeric: tabular-nums;
  min-width: 30px;
  text-align: right;
}

/* ── v3 今日热门股池 ── */
.top-picks-list {
  display: flex;
  flex-direction: column;
  max-height: 420px;
  overflow-y: auto;
}
.top-pick-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--color-divider);
  font-size: var(--text-sm);
}
.top-pick-row:last-child { border-bottom: none; }
.top-pick-rank {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  min-width: 32px;
}
.top-pick-code {
  font-family: var(--font-mono);
  font-weight: var(--weight-semibold);
  min-width: 50px;
}
.top-pick-name {
  color: var(--color-text-secondary);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.top-pick-tag {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--color-up-soft);
  color: var(--color-up);
}
.top-pick-sentiment {
  margin-left: auto;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: var(--weight-medium);
  border: 1px solid transparent;
  white-space: nowrap;
}
.top-pick-sentiment--bull {
  background: rgba(225, 29, 72, 0.10);
  color: var(--color-up);
  border-color: rgba(225, 29, 72, 0.22);
}
.top-pick-sentiment--bear {
  background: rgba(16, 185, 129, 0.10);
  color: var(--color-down);
  border-color: rgba(16, 185, 129, 0.22);
}
.top-pick-sentiment--neutral {
  background: rgba(245, 158, 11, 0.10);
  color: var(--color-warning);
  border-color: rgba(245, 158, 11, 0.22);
}
.top-pick-sentiment--empty {
  background: var(--color-bg-muted);
  color: var(--color-text-tertiary);
  border-color: var(--color-divider);
}

/* ── 帖子缓存查看器（v3, 2026-06-04）── */
.post-dialog__loading,
.post-dialog__error {
  padding: var(--space-4);
  text-align: center;
  color: var(--color-text-tertiary);
}
.post-dialog__error { color: var(--color-danger); }
.post-dialog__meta {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}
.post-dialog__author { font-weight: var(--weight-medium); }
.post-dialog__time { color: var(--color-text-tertiary); }
.post-dialog__title-diff {
  padding: var(--space-3);
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-sm);
  margin-bottom: var(--space-3);
  font-size: var(--text-xs);
  line-height: 1.6;
}
.post-dialog__label {
  color: var(--color-text-tertiary);
  margin-right: 6px;
}
.post-dialog__body {
  white-space: pre-wrap;
  line-height: 1.7;
  max-height: 50vh;
  overflow-y: auto;
  padding: var(--space-3);
  background: var(--color-bg-elevated);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
}
.post-dialog__empty {
  padding: var(--space-4);
  background: var(--color-bg-elevated);
  border-radius: var(--radius-sm);
  text-align: center;
}
.post-dialog__hint {
  margin-top: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}
.post-dialog__actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-3);
  justify-content: flex-end;
}

.index-filter {
  margin-right: 12px;
}
.index-filter :deep(.el-radio-button__inner) {
  padding: 5px 10px;
  font-size: 12px;
}

/* ── 批量分析进度条（v4, 2026-06-08） ── */
.batch-progress {
  margin: 0 0 var(--space-5) 0;
  padding: 14px 18px;
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, rgba(99,102,241,0.06), rgba(99,102,241,0.02));
  border: 1px solid rgba(99,102,241,0.22);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.batch-progress--universe {
  background: linear-gradient(135deg, rgba(245,158,11,0.06), rgba(245,158,11,0.02));
  border-color: rgba(245,158,11,0.22);
}
.batch-progress__head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.batch-progress__title {
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.batch-progress__pulse {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-accent);
  position: relative;
}
.batch-progress__pulse::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: var(--color-accent);
  animation: pulse-ring 1.8s var(--ease) infinite;
  z-index: -1;
}
@keyframes pulse-ring {
  0%   { transform: scale(1);   opacity: 0.6; }
  100% { transform: scale(2.8); opacity: 0;   }
}
.batch-progress__count {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  font-variant-numeric: tabular-nums;
}
.batch-progress__count strong {
  color: var(--color-text-primary);
  font-weight: var(--weight-bold);
  font-size: 16px;
}
.batch-progress__count .muted { color: var(--color-text-tertiary); }
.batch-progress__count .warn {
  color: var(--color-danger);
  font-weight: var(--weight-semibold);
  margin-left: 6px;
}
.batch-progress__detail {
  display: flex;
  justify-content: space-between;
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}
.batch-progress__current code {
  font-family: var(--font-mono);
  background: var(--color-bg-muted);
  padding: 1px 6px;
  border-radius: 4px;
  color: var(--color-text-primary);
}
.batch-progress__name {
  margin-left: 6px;
  color: var(--color-text-primary);
  font-weight: var(--weight-medium);
}
.batch-progress__stuck {
  margin-left: 10px;
  padding: 1px 8px;
  border-radius: 999px;
  background: rgba(234, 88, 12, 0.12);
  color: #ea580c;
  font-size: 12px;
  font-weight: var(--weight-semibold);
  animation: pulse-stuck 1.2s ease-in-out infinite;
}
@keyframes pulse-stuck {
  0%, 100% { opacity: 0.7; }
  50% { opacity: 1; }
}
.batch-progress__done { color: var(--color-success, #16a34a); font-weight: var(--weight-semibold); }
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s var(--ease); }
.fade-enter-from, .fade-leave-to { opacity: 0; }

/* ── v7 顶部状态总览（2026-06-29）── */
.overview-card { margin-top: 0; }
.overview {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  flex-wrap: wrap;
}
.overview__verdict {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 160px;
}
.overview__verdict-label {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-weight: var(--weight-medium);
}
.overview__verdict-text {
  font-size: 22px;
  font-weight: var(--weight-bold);
  letter-spacing: -0.02em;
  line-height: 1.1;
}
.verdict--bull { color: var(--color-up); }
.verdict--bear { color: var(--color-down); }
.verdict--neutral { color: var(--color-warning); }
.overview__verdict-detail {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  margin-top: 2px;
}
.overview__metrics {
  display: flex;
  gap: var(--space-5);
  flex: 1;
  flex-wrap: wrap;
  border-left: 1px solid var(--color-divider);
  padding-left: var(--space-5);
}
.ov-metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 96px;
}
.ov-metric__label {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-weight: var(--weight-medium);
}
.ov-metric strong {
  font-size: 20px;
  font-weight: var(--weight-bold);
  letter-spacing: -0.02em;
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
}
.ov-metric__total {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text-tertiary);
}
.ov-metric__muted { color: var(--color-text-tertiary); font-size: var(--text-md); }
.ov-extreme { color: var(--color-down); }
.overview__jobs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.overview__alerts {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px dashed var(--color-divider);
}
.alert-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 999px;
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  border: 1px solid transparent;
}
.alert-chip--circuit { cursor: pointer; }
.alert-chip--warning {
  background: rgba(245, 158, 11, 0.12);
  color: var(--color-warning);
  border-color: rgba(245, 158, 11, 0.28);
}
.alert-chip--danger {
  background: rgba(239, 68, 68, 0.12);
  color: var(--color-danger);
  border-color: rgba(239, 68, 68, 0.28);
}
.alert-chip--stale {
  background: rgba(234, 88, 12, 0.10);
  color: #ea580c;
  border-color: rgba(234, 88, 12, 0.28);
}
.alert-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: currentColor;
}

/* ── v7 tabs ── */
.sentiment-tabs {
  margin-top: 0;
}
.sentiment-tabs :deep(.el-tabs__header) {
  margin-bottom: var(--space-4);
}
.sentiment-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
  background: var(--color-divider);
}
.sentiment-tabs :deep(.el-tabs__item) {
  font-weight: var(--weight-medium);
  font-size: var(--text-sm);
}

@media (max-width: 720px) {
  .overview__metrics {
    border-left: none;
    padding-left: 0;
    border-top: 1px solid var(--color-divider);
    padding-top: var(--space-3);
    width: 100%;
  }
}
</style>
