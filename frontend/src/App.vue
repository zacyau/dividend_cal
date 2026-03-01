<template>
  <div class="app">
    <header class="header">
      <h1>股票分红计算器</h1>
      <p class="subtitle">计算股票分红回本周期</p>
    </header>

    <main class="main">
      <section class="search-section">
        <div class="search-box">
          <div class="input-group">
            <label>股票代码/名称</label>
            <input
              v-model="searchKeyword"
              @input="debouncedSearch"
              placeholder="输入股票代码或名称搜索"
              class="input"
            />
            <div v-if="searchResults.length > 0" class="search-results">
              <div
                v-for="stock in searchResults"
                :key="stock.代码"
                @click="selectStock(stock)"
                class="search-item"
              >
                <span class="stock-code">{{ stock.代码 }}</span>
                <span class="stock-name">{{ stock.名称 }}</span>
              </div>
            </div>
          </div>

          <div class="input-group">
            <label>买入年份</label>
            <input
              v-model="buyYear"
              type="number"
              placeholder="例如: 2015"
              class="input"
              min="1990"
              max="2024"
            />
          </div>

          <div class="input-group">
            <label>买入价格（可选）</label>
            <input
              v-model="buyPrice"
              type="number"
              placeholder="留空则自动获取当年价格"
              class="input"
              step="0.01"
            />
          </div>

          <div class="input-group">
            <label>买入股数</label>
            <input
              v-model="buyShares"
              type="number"
              placeholder="例如: 1000"
              class="input"
              min="1"
              step="100"
            />
          </div>

          <button
            @click="calculate"
            :disabled="!selectedStock || !buyYear || !buyShares || loading"
            class="btn btn-primary"
          >
            {{ loading ? '计算中...' : '开始计算' }}
          </button>
        </div>

        <div v-if="selectedStock" class="selected-stock">
          <span class="stock-badge">
            {{ selectedStock.代码 }} - {{ selectedStock.名称 }}
          </span>
        </div>
      </section>

      <section v-if="error" class="error-section">
        <div class="error-message">{{ error }}</div>
      </section>

      <section v-if="result" class="result-section">
        <div class="result-header">
          <h2>计算结果</h2>
          <div class="result-summary">
            <div class="summary-item">
              <span class="label">股票代码</span>
              <span class="value">{{ result.stock_code }}</span>
            </div>
            <div class="summary-item">
              <span class="label">买入年份</span>
              <span class="value">{{ result.buy_year }}</span>
            </div>
            <div class="summary-item">
              <span class="label">买入价格</span>
              <span class="value">¥{{ result.buy_price.toFixed(2) }}</span>
            </div>
            <div class="summary-item">
              <span class="label">买入股数</span>
              <span class="value">{{ result.buy_shares }} 股</span>
            </div>
            <div class="summary-item">
              <span class="label">买入成本</span>
              <span class="value highlight">¥{{ result.total_cost.toFixed(2) }}</span>
            </div>
          </div>
        </div>

        <div class="comparison-cards">
          <div class="card card-without">
            <h3>红利不再投入</h3>
            <div class="card-content">
              <div class="stat">
                <span class="stat-label">回本年限</span>
                <span class="stat-value" :class="{ 'not-achieved': !result.without_reinvest.years_to_payback }">
                  {{ result.without_reinvest.years_to_payback ? result.without_reinvest.years_to_payback + ' 年' : '尚未回本' }}
                </span>
              </div>
              <div class="stat">
                <span class="stat-label">累计现金分红</span>
                <span class="stat-value">¥{{ result.without_reinvest.total_dividend.toFixed(2) }}</span>
              </div>
              <div class="stat">
                <span class="stat-label">最终股数</span>
                <span class="stat-value">{{ result.without_reinvest.final_shares }} 股</span>
              </div>
              <div class="stat">
                <span class="stat-label">回本比例</span>
                <span class="stat-value">{{ result.without_reinvest.payback_ratio }}%</span>
              </div>
            </div>
          </div>

          <div class="card card-with">
            <h3>红利再投入</h3>
            <div class="card-content">
              <div class="stat">
                <span class="stat-label">回本年限</span>
                <span class="stat-value" :class="{ 'not-achieved': !result.with_reinvest.years_to_payback }">
                  {{ result.with_reinvest.years_to_payback ? result.with_reinvest.years_to_payback + ' 年' : '尚未回本' }}
                </span>
              </div>
              <div class="stat">
                <span class="stat-label">累计现金分红</span>
                <span class="stat-value">¥{{ result.with_reinvest.total_dividend.toFixed(2) }}</span>
              </div>
              <div class="stat">
                <span class="stat-label">再投入金额</span>
                <span class="stat-value">¥{{ result.with_reinvest.total_reinvested.toFixed(2) }}</span>
              </div>
              <div class="stat">
                <span class="stat-label">剩余现金</span>
                <span class="stat-value">¥{{ result.with_reinvest.remaining_cash.toFixed(2) }}</span>
              </div>
              <div class="stat">
                <span class="stat-label">最终股数</span>
                <span class="stat-value">{{ result.with_reinvest.final_shares }} 股</span>
              </div>
              <div class="stat">
                <span class="stat-label">回本比例</span>
                <span class="stat-value">{{ result.with_reinvest.payback_ratio }}%</span>
              </div>
            </div>
          </div>
        </div>

        <div class="chart-section">
          <h3>累计现金分红对比图</h3>
          <div class="chart-container">
            <Line :data="chartData" :options="chartOptions" />
          </div>
        </div>

        <div class="table-section">
          <h3>年度分红明细</h3>
          <div class="table-container">
            <table class="data-table">
              <thead>
                <tr>
                  <th>年份</th>
                  <th>每股现金</th>
                  <th>每股送股</th>
                  <th>每股转增</th>
                  <th>不再投入<br/>当年现金分红</th>
                  <th>不再投入<br/>累计现金</th>
                  <th>不再投入<br/>最终股数</th>
                  <th>再投入<br/>当年现金分红</th>
                  <th>再投入<br/>累计现金</th>
                  <th>再投入<br/>买入股数</th>
                  <th>再投入<br/>剩余现金</th>
                  <th>再投入<br/>最终股数</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(item, index) in result.without_reinvest.yearly_data" :key="item.year">
                  <td>{{ item.year }}</td>
                  <td>¥{{ item.cash_per_share.toFixed(2) }}</td>
                  <td>{{ item.stock_bonus_per_share.toFixed(2) }}</td>
                  <td>{{ item.stock_transfer_per_share.toFixed(2) }}</td>
                  <td>¥{{ item.yearly_cash_dividend.toFixed(2) }}</td>
                  <td>¥{{ item.total_cash_dividend.toFixed(2) }}</td>
                  <td>{{ item.shares_after }} 股</td>
                  <td>¥{{ result.with_reinvest.yearly_data[index]?.yearly_cash_dividend.toFixed(2) || '0.00' }}</td>
                  <td>¥{{ result.with_reinvest.yearly_data[index]?.total_cash_dividend.toFixed(2) || '0.00' }}</td>
                  <td>{{ result.with_reinvest.yearly_data[index]?.new_shares_from_reinvest || 0 }} 股</td>
                  <td>¥{{ result.with_reinvest.yearly_data[index]?.cash_balance.toFixed(2) || '0.00' }}</td>
                  <td>{{ result.with_reinvest.yearly_data[index]?.shares_after || result.buy_shares }} 股</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </main>

    <footer class="footer">
      <p>数据来源: akshare | 仅供参考，不构成投资建议</p>
    </footer>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import axios from 'axios'
import { Line } from 'vue-chartjs'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend
} from 'chart.js'

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend
)

const searchKeyword = ref('')
const searchResults = ref([])
const selectedStock = ref(null)
const buyYear = ref('')
const buyPrice = ref('')
const buyShares = ref('1000')
const loading = ref(false)
const error = ref('')
const result = ref(null)

let searchTimeout = null

const debouncedSearch = () => {
  clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => {
    if (searchKeyword.value.length >= 1) {
      searchStock()
    } else {
      searchResults.value = []
    }
  }, 300)
}

const searchStock = async () => {
  try {
    const response = await axios.get(`/api/search_stock?keyword=${searchKeyword.value}`)
    if (response.data.success) {
      searchResults.value = response.data.data
    }
  } catch (err) {
    console.error('搜索失败:', err)
  }
}

const selectStock = (stock) => {
  selectedStock.value = stock
  searchKeyword.value = stock.代码
  searchResults.value = []
}

const calculate = async () => {
  if (!selectedStock.value || !buyYear.value || !buyShares.value) return
  
  loading.value = true
  error.value = ''
  result.value = null
  
  try {
    const response = await axios.post('/api/calculate', {
      stock_code: selectedStock.value.代码,
      buy_year: parseInt(buyYear.value),
      buy_price: buyPrice.value || null,
      buy_shares: parseInt(buyShares.value)
    })
    
    if (response.data.success) {
      result.value = response.data.data
    } else {
      error.value = response.data.error
    }
  } catch (err) {
    error.value = err.response?.data?.error || '计算失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

const chartData = computed(() => {
  if (!result.value) return { labels: [], datasets: [] }
  
  const labels = result.value.without_reinvest.yearly_data.map(item => item.year)
  const totalCost = result.value.total_cost
  
  return {
    labels,
    datasets: [
      {
        label: '不再投入累计现金分红',
        data: result.value.without_reinvest.yearly_data.map(item => item.total_cash_dividend),
        borderColor: '#6366f1',
        backgroundColor: 'rgba(99, 102, 241, 0.1)',
        tension: 0.3,
        fill: true
      },
      {
        label: '再投入累计现金分红',
        data: result.value.with_reinvest.yearly_data.map(item => item.total_cash_dividend),
        borderColor: '#10b981',
        backgroundColor: 'rgba(16, 185, 129, 0.1)',
        tension: 0.3,
        fill: true
      },
      {
        label: '买入成本',
        data: labels.map(() => totalCost),
        borderColor: '#ef4444',
        borderDash: [5, 5],
        borderWidth: 2,
        pointRadius: 0,
        fill: false
      }
    ]
  }
})

const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      position: 'top'
    },
    tooltip: {
      callbacks: {
        label: function(context) {
          return `${context.dataset.label}: ¥${context.parsed.y.toFixed(2)}`
        }
      }
    }
  },
  scales: {
    y: {
      beginAtZero: true,
      ticks: {
        callback: function(value) {
          return '¥' + value
        }
      }
    }
  }
}
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  min-height: 100vh;
}

.app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.header {
  text-align: center;
  padding: 40px 20px;
  color: white;
}

.header h1 {
  font-size: 2.5rem;
  font-weight: 700;
  margin-bottom: 10px;
  text-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);
}

.subtitle {
  font-size: 1.1rem;
  opacity: 0.9;
}

.main {
  flex: 1;
  max-width: 1400px;
  width: 100%;
  margin: 0 auto;
  padding: 0 20px 40px;
}

.search-section {
  background: white;
  border-radius: 20px;
  padding: 30px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.15);
  margin-bottom: 30px;
}

.search-box {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 20px;
  align-items: end;
}

.input-group {
  position: relative;
}

.input-group label {
  display: block;
  margin-bottom: 8px;
  font-weight: 600;
  color: #374151;
  font-size: 0.9rem;
}

.input {
  width: 100%;
  padding: 12px 16px;
  border: 2px solid #e5e7eb;
  border-radius: 10px;
  font-size: 1rem;
  transition: all 0.3s ease;
}

.input:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.search-results {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  background: white;
  border: 2px solid #e5e7eb;
  border-radius: 10px;
  margin-top: 5px;
  max-height: 200px;
  overflow-y: auto;
  z-index: 100;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
}

.search-item {
  padding: 12px 16px;
  cursor: pointer;
  display: flex;
  gap: 15px;
  transition: background 0.2s;
}

.search-item:hover {
  background: #f3f4f6;
}

.stock-code {
  font-weight: 600;
  color: #6366f1;
}

.stock-name {
  color: #6b7280;
}

.btn {
  padding: 12px 24px;
  border: none;
  border-radius: 10px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
}

.btn-primary {
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 5px 20px rgba(99, 102, 241, 0.4);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.selected-stock {
  margin-top: 20px;
}

.stock-badge {
  display: inline-block;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: white;
  padding: 8px 16px;
  border-radius: 20px;
  font-weight: 600;
}

.error-section {
  margin-bottom: 30px;
}

.error-message {
  background: #fef2f2;
  color: #dc2626;
  padding: 16px 20px;
  border-radius: 10px;
  border: 1px solid #fecaca;
}

.result-section {
  background: white;
  border-radius: 20px;
  padding: 30px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.15);
}

.result-header {
  margin-bottom: 30px;
}

.result-header h2 {
  font-size: 1.5rem;
  color: #1f2937;
  margin-bottom: 20px;
}

.result-summary {
  display: flex;
  gap: 30px;
  flex-wrap: wrap;
}

.summary-item {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.summary-item .label {
  font-size: 0.85rem;
  color: #6b7280;
}

.summary-item .value {
  font-size: 1.1rem;
  font-weight: 600;
  color: #1f2937;
}

.summary-item .value.highlight {
  color: #6366f1;
  font-size: 1.2rem;
}

.comparison-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 20px;
  margin-bottom: 40px;
}

.card {
  background: #f9fafb;
  border-radius: 15px;
  padding: 25px;
  border: 2px solid transparent;
}

.card-without {
  border-color: #6366f1;
}

.card-with {
  border-color: #10b981;
}

.card h3 {
  font-size: 1.2rem;
  margin-bottom: 20px;
  padding-bottom: 10px;
  border-bottom: 2px solid #e5e7eb;
}

.card-without h3 {
  color: #6366f1;
}

.card-with h3 {
  color: #10b981;
}

.card-content {
  display: flex;
  flex-direction: column;
  gap: 15px;
}

.stat {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.stat-label {
  color: #6b7280;
  font-size: 0.95rem;
}

.stat-value {
  font-weight: 700;
  font-size: 1.1rem;
  color: #1f2937;
}

.stat-value.not-achieved {
  color: #ef4444;
}

.chart-section {
  margin-bottom: 40px;
}

.chart-section h3 {
  font-size: 1.2rem;
  color: #1f2937;
  margin-bottom: 20px;
}

.chart-container {
  height: 400px;
  background: #f9fafb;
  border-radius: 15px;
  padding: 20px;
}

.table-section h3 {
  font-size: 1.2rem;
  color: #1f2937;
  margin-bottom: 20px;
}

.table-container {
  overflow-x: auto;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}

.data-table th,
.data-table td {
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid #e5e7eb;
  white-space: nowrap;
}

.data-table th {
  background: #f9fafb;
  font-weight: 600;
  color: #374151;
}

.data-table tr:hover {
  background: #f9fafb;
}

.footer {
  text-align: center;
  padding: 20px;
  color: white;
  opacity: 0.8;
  font-size: 0.9rem;
}

@media (max-width: 768px) {
  .header h1 {
    font-size: 1.8rem;
  }
  
  .search-box {
    grid-template-columns: 1fr;
  }
  
  .result-summary {
    flex-direction: column;
    gap: 15px;
  }
}
</style>
