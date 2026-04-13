'use client'

import { useEffect, useMemo, useState } from 'react'
import type React from 'react'
import { supabase } from '@/lib/supabaseClient'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts'

type OrderRow = {
  id: number
  external_id: string | null
  order_number: string | null
  created_at: string | null
  status: string | null
  total_sum: number | null
  customer_name: string | null
  customer_phone: string | null
  customer_email: string | null
  items_count: number | null
}

type OrderItemRow = {
  id: number
  order_external_id: string | null
  item_index: number | null
  offer_id: string | null
  product_name: string | null
  product_article: string | null
  quantity: number | null
  initial_price: number | null
  line_total: number | null
}

type DailyPoint = {
  date: string
  revenue: number
  orders: number
}

type StatusPoint = {
  name: string
  value: number
}

type ProductPoint = {
  product_name: string
  qty: number
  revenue: number
}

const PIE_COLORS = [
  '#3b82f6',
  '#10b981',
  '#f59e0b',
  '#ef4444',
  '#8b5cf6',
  '#06b6d4',
  '#84cc16',
  '#f97316',
]

export default function HomePage() {
  const [orders, setOrders] = useState<OrderRow[]>([])
  const [items, setItems] = useState<OrderItemRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [search, setSearch] = useState('')

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      setError(null)

      const ordersQuery = supabase
        .from('orders')
        .select(
          'id, external_id, order_number, created_at, status, total_sum, customer_name, customer_phone, customer_email, items_count'
        )
        .order('created_at', { ascending: true })

      const itemsQuery = supabase
        .from('order_items')
        .select(
          'id, order_external_id, item_index, offer_id, product_name, product_article, quantity, initial_price, line_total'
        )
        .order('id', { ascending: true })

      const [ordersRes, itemsRes] = await Promise.all([ordersQuery, itemsQuery])

      if (ordersRes.error) {
        console.error(ordersRes.error)
        setError(ordersRes.error.message)
        setLoading(false)
        return
      }

      if (itemsRes.error) {
        console.error(itemsRes.error)
        setError(itemsRes.error.message)
        setLoading(false)
        return
      }

      setOrders((ordersRes.data || []) as OrderRow[])
      setItems((itemsRes.data || []) as OrderItemRow[])
      setLoading(false)
    }

    load()
  }, [])

  const filteredOrders = useMemo(() => {
    const q = search.trim().toLowerCase()

    return orders.filter(order => {
      const matchesStatus =
        statusFilter === 'all' ? true : (order.status || '—') === statusFilter

      const haystack = [
        order.external_id,
        order.order_number,
        order.customer_name,
        order.customer_phone,
        order.customer_email,
        order.status,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()

      const matchesSearch = q ? haystack.includes(q) : true

      return matchesStatus && matchesSearch
    })
  }, [orders, statusFilter, search])

  const filteredOrderIds = useMemo(() => {
    return new Set(
      filteredOrders
        .map(order => order.external_id)
        .filter((v): v is string => Boolean(v))
    )
  }, [filteredOrders])

  const filteredItems = useMemo(() => {
    return items.filter(item =>
      item.order_external_id ? filteredOrderIds.has(item.order_external_id) : false
    )
  }, [items, filteredOrderIds])

const stats = useMemo(() => {
  const totalOrders = filteredOrders.length
  const totalRevenue = filteredOrders.reduce(
    (sum, o) => sum + Number(o.total_sum || 0),
    0
  )
  const avgOrder = totalOrders ? totalRevenue / totalOrders : 0
  const bigOrders = filteredOrders.filter(o => Number(o.total_sum || 0) > 50000).length

  const totalUnits = filteredItems.reduce(
    (sum, item) => sum + Number(item.quantity || 0),
    0
  )

  const totalLineItems = filteredItems.length

  const uniqueProducts = new Set(
    filteredItems.map(
      item =>
        item.product_article ||
        item.product_name ||
        item.offer_id ||
        'unknown'
    )
  ).size

  return {
    totalOrders,
    totalRevenue,
    avgOrder,
    bigOrders,
    totalUnits,
    totalLineItems,
    uniqueProducts,
  }
}, [filteredOrders, filteredItems])

  const dailyData = useMemo<DailyPoint[]>(() => {
    const byDate: Record<string, { revenue: number; orders: number }> = {}

    for (const order of filteredOrders) {
      if (!order.created_at) continue
      const key = new Date(order.created_at).toISOString().slice(0, 10)

      if (!byDate[key]) {
        byDate[key] = { revenue: 0, orders: 0 }
      }

      byDate[key].revenue += Number(order.total_sum || 0)
      byDate[key].orders += 1
    }

    return Object.entries(byDate)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, value]) => ({
        date,
        revenue: value.revenue,
        orders: value.orders,
      }))
  }, [filteredOrders])

  const statusData = useMemo<StatusPoint[]>(() => {
    const map = new Map<string, number>()

    for (const order of filteredOrders) {
      const key = order.status || '—'
      map.set(key, (map.get(key) || 0) + 1)
    }

    return Array.from(map.entries())
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)
  }, [filteredOrders])

  const topProducts = useMemo<ProductPoint[]>(() => {
    const map = new Map<string, { qty: number; revenue: number }>()

    for (const item of filteredItems) {
      const key =
        item.product_name ||
        item.product_article ||
        item.offer_id ||
        'Без названия'

      const prev = map.get(key) || { qty: 0, revenue: 0 }
      prev.qty += Number(item.quantity || 0)
      prev.revenue += Number(item.line_total || 0)
      map.set(key, prev)
    }

    return Array.from(map.entries())
      .map(([product_name, value]) => ({
        product_name,
        qty: value.qty,
        revenue: value.revenue,
      }))
      .sort((a, b) => b.revenue - a.revenue)
      .slice(0, 10)
  }, [filteredItems])

  const topProductsByQty = useMemo(() => {
  const map = new Map<string, { qty: number; revenue: number }>()

  for (const item of filteredItems) {
    const key =
      item.product_name ||
      item.product_article ||
      item.offer_id ||
      'Без названия'

    const prev = map.get(key) || { qty: 0, revenue: 0 }
    prev.qty += Number(item.quantity || 0)
    prev.revenue += Number(item.line_total || 0)
    map.set(key, prev)
  }

  return Array.from(map.entries())
    .map(([product_name, value]) => ({
      product_name,
      qty: value.qty,
      revenue: value.revenue,
    }))
    .sort((a, b) => b.qty - a.qty)
    .slice(0, 10)
}, [filteredItems])

const avgCheckByDay = useMemo(() => {
  const byDate: Record<string, { revenue: number; orders: number }> = {}

  for (const order of filteredOrders) {
    if (!order.created_at) continue
    const key = new Date(order.created_at).toISOString().slice(0, 10)

    if (!byDate[key]) {
      byDate[key] = { revenue: 0, orders: 0 }
    }

    byDate[key].revenue += Number(order.total_sum || 0)
    byDate[key].orders += 1
  }

  return Object.entries(byDate)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, value]) => ({
      date,
      avgCheck: value.orders ? value.revenue / value.orders : 0,
    }))
}, [filteredOrders])

const bigOrders = useMemo(() => {
  return [...filteredOrders]
    .filter(order => Number(order.total_sum || 0) > 50000)
    .sort((a, b) => Number(b.total_sum || 0) - Number(a.total_sum || 0))
    .slice(0, 20)
}, [filteredOrders])

const statusBarData = useMemo(() => {
  const map = new Map<string, number>()

  for (const order of filteredOrders) {
    const key = order.status || '—'
    map.set(key, (map.get(key) || 0) + 1)
  }

  return Array.from(map.entries())
    .map(([status, count]) => ({ status, count }))
    .sort((a, b) => b.count - a.count)
}, [filteredOrders])

  const latestOrders = useMemo(() => {
    return [...filteredOrders]
      .sort((a, b) => {
        const ad = a.created_at ? new Date(a.created_at).getTime() : 0
        const bd = b.created_at ? new Date(b.created_at).getTime() : 0
        return bd - ad
      })
      .slice(0, 20)
  }, [filteredOrders])

  const latestItems = useMemo(() => {
    return [...filteredItems]
      .slice(-30)
      .reverse()
  }, [filteredItems])

  const availableStatuses = useMemo(() => {
    return Array.from(new Set(orders.map(o => o.status || '—'))).sort()
  }, [orders])

  if (loading) {
    return (
      <main style={pageStyle}>
        <h1 style={pageTitle}>RetailCRM Dashboard</h1>
        <p style={mutedText}>Загрузка данных...</p>
      </main>
    )
  }

  if (error) {
    return (
      <main style={pageStyle}>
        <h1 style={pageTitle}>RetailCRM Dashboard</h1>
        <div style={errorBoxStyle}>Ошибка: {error}</div>
      </main>
    )
  }

  return (
    <main style={pageStyle}>
      <div style={headerRowStyle}>
        <div>
          <h1 style={pageTitle}>RetailCRM Dashboard</h1>
          <p style={mutedText}>
            Полный дашборд по заказам, товарам и выручке из Supabase
          </p>
        </div>
      </div>

      <section style={filtersWrapStyle}>
        <div style={filterBlockStyle}>
          <label style={labelStyle}>Поиск</label>
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="ID заказа, клиент, телефон, email..."
            style={inputStyle}
          />
        </div>

        <div style={filterBlockStyle}>
          <label style={labelStyle}>Статус</label>
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            style={inputStyle}
          >
            <option value="all">Все статусы</option>
            {availableStatuses.map(status => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </div>
      </section>

      <section style={statsGridStyle}>
  <StatCard title="Заказы" value={stats.totalOrders.toLocaleString()} />
  <StatCard title="Выручка" value={formatCurrency(stats.totalRevenue)} />
  <StatCard title="Средний чек" value={formatCurrency(stats.avgOrder)} />
  <StatCard title="Заказы > 50 000 ₸" value={stats.bigOrders.toLocaleString()} />
  <StatCard title="Строк позиций" value={stats.totalLineItems.toLocaleString()} />
  <StatCard title="Товарных единиц" value={stats.totalUnits.toLocaleString()} />
  <StatCard title="Уникальных товаров" value={stats.uniqueProducts.toLocaleString()} />
</section>

      <section style={twoColGridStyle}>
        <ChartCard
          title="Выручка по дням"
          subtitle="Суммарная выручка по датам создания заказа"
        >
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={dailyData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis />
              <Tooltip formatter={value => [formatCurrency(Number(value)), 'Выручка']} />
              <Legend />
              <Line
                type="monotone"
                dataKey="revenue"
                name="Выручка"
                stroke="#2563eb"
                strokeWidth={3}
                dot={{ r: 3 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard
          title="Количество заказов по дням"
          subtitle="Сколько заказов создавалось в каждый день"
        >
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={dailyData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis />
              <Tooltip formatter={value => [value, 'Заказы']} />
              <Legend />
              <Bar dataKey="orders" name="Заказы" fill="#10b981" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </section>

      <section style={twoColGridStyle}>
        <ChartCard
          title="Статусы заказов"
          subtitle="Распределение заказов по статусам"
        >
          <ResponsiveContainer width="100%" height={320}>
            <PieChart>
              <Pie
                data={statusData}
                dataKey="value"
                nameKey="name"
                outerRadius={110}
                label
              >
                {statusData.map((entry, index) => (
                  <Cell key={`${entry.name}-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard
          title="Топ товаров"
          subtitle="Товары с максимальной выручкой"
        >
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={topProducts} layout="vertical" margin={{ left: 24 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis
                dataKey="product_name"
                type="category"
                width={180}
                tick={{ fontSize: 12 }}
              />
              <Tooltip
                formatter={(value, name) => {
                  if (name === 'revenue') return [formatCurrency(Number(value)), 'Выручка']
                  return [value, 'Количество']
                }}
              />
              <Legend />
              <Bar dataKey="revenue" name="revenue" fill="#f59e0b" radius={[0, 6, 6, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </section>

      <section style={twoColGridStyle}>
  <ChartCard
    title="Средний чек по дням"
    subtitle="Средняя сумма заказа по дням"
  >
    <ResponsiveContainer width="100%" height={320}>
      <LineChart data={avgCheckByDay}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="date" />
        <YAxis />
        <Tooltip formatter={value => [formatCurrency(Number(value)), 'Средний чек']} />
        <Legend />
        <Line
          type="monotone"
          dataKey="avgCheck"
          name="Средний чек"
          stroke="#8b5cf6"
          strokeWidth={3}
          dot={{ r: 3 }}
        />
      </LineChart>
    </ResponsiveContainer>
  </ChartCard>

  <ChartCard
    title="Количество заказов по статусам"
    subtitle="Столбчатый график по статусам заказов"
  >
    <ResponsiveContainer width="100%" height={320}>
      <BarChart data={statusBarData}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="status" />
        <YAxis />
        <Tooltip formatter={value => [value, 'Заказы']} />
        <Legend />
        <Bar dataKey="count" name="Количество" fill="#06b6d4" radius={[6, 6, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  </ChartCard>
</section>

<section style={twoColGridStyle}>
  <ChartCard
    title="Топ товаров по количеству"
    subtitle="Какие товары покупают чаще всего"
  >
    <ResponsiveContainer width="100%" height={320}>
      <BarChart data={topProductsByQty} layout="vertical" margin={{ left: 24 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis type="number" />
        <YAxis
          dataKey="product_name"
          type="category"
          width={180}
          tick={{ fontSize: 12 }}
        />
        <Tooltip formatter={(value) => [value, 'Количество']} />
        <Legend />
        <Bar dataKey="qty" name="Количество" fill="#22c55e" radius={[0, 6, 6, 0]} />
      </BarChart>
    </ResponsiveContainer>
  </ChartCard>

  <Panel
    title="Крупные заказы"
    subtitle="Заказы с суммой больше 50 000 ₸"
  >
    <div style={tableWrapStyle}>
      <table style={tableStyle}>
        <thead>
          <tr style={theadRowStyle}>
            <th style={thStyle}>Заказ</th>
            <th style={thStyle}>Клиент</th>
            <th style={thStyle}>Дата</th>
            <th style={thStyle}>Статус</th>
            <th style={thStyleRight}>Сумма</th>
          </tr>
        </thead>
        <tbody>
          {bigOrders.map(order => (
            <tr key={order.id}>
              <td style={tdStyle}>
                {order.order_number || order.external_id || order.id}
              </td>
              <td style={tdStyle}>{order.customer_name || '—'}</td>
              <td style={tdStyle}>
                {order.created_at
                  ? new Date(order.created_at).toLocaleString()
                  : '—'}
              </td>
              <td style={tdStyle}>{order.status || '—'}</td>
              <td style={tdStyleRight}>
                {formatCurrency(order.total_sum || 0)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </Panel>
</section>


      <section style={twoColGridStyle}>
        <Panel title="Последние заказы" subtitle="20 последних заказов">
          <div style={tableWrapStyle}>
            <table style={tableStyle}>
              <thead>
                <tr style={theadRowStyle}>
                  <th style={thStyle}>Заказ</th>
                  <th style={thStyle}>Клиент</th>
                  <th style={thStyle}>Дата</th>
                  <th style={thStyle}>Статус</th>
                  <th style={thStyleRight}>Сумма</th>
                </tr>
              </thead>
              <tbody>
                {latestOrders.map(order => (
                  <tr key={order.id}>
                    <td style={tdStyle}>
                      {order.order_number || order.external_id || order.id}
                    </td>
                    <td style={tdStyle}>{order.customer_name || '—'}</td>
                    <td style={tdStyle}>
                      {order.created_at
                        ? new Date(order.created_at).toLocaleString()
                        : '—'}
                    </td>
                    <td style={tdStyle}>{order.status || '—'}</td>
                    <td style={tdStyleRight}>{formatCurrency(order.total_sum || 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel title="Последние позиции" subtitle="30 последних товарных позиций">
          <div style={tableWrapStyle}>
            <table style={tableStyle}>
              <thead>
                <tr style={theadRowStyle}>
                  <th style={thStyle}>Заказ</th>
                  <th style={thStyle}>Товар</th>
                  <th style={thStyle}>Артикул</th>
                  <th style={thStyleRight}>Кол-во</th>
                  <th style={thStyleRight}>Сумма</th>
                </tr>
              </thead>
              <tbody>
                {latestItems.map((item, index) => (
                  <tr key={`${item.order_external_id}-${item.item_index}-${index}`}>
                    <td style={tdStyle}>{item.order_external_id || '—'}</td>
                    <td style={tdStyle}>{item.product_name || '—'}</td>
                    <td style={tdStyle}>{item.product_article || '—'}</td>
                    <td style={tdStyleRight}>{Number(item.quantity || 0)}</td>
                    <td style={tdStyleRight}>{formatCurrency(item.line_total || 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </section>
    </main>
  )
}

function StatCard({ title, value }: { title: string; value: string }) {
  return (
    <div style={statCardStyle}>
      <div style={statTitleStyle}>{title}</div>
      <div style={statValueStyle}>{value}</div>
    </div>
  )
}

function ChartCard({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle: string
  children: React.ReactNode
}) {
  return (
    <section style={panelStyle}>
      <h2 style={panelTitleStyle}>{title}</h2>
      <p style={panelSubtitleStyle}>{subtitle}</p>
      {children}
    </section>
  )
}

function Panel({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle: string
  children: React.ReactNode
}) {
  return (
    <section style={panelStyle}>
      <h2 style={panelTitleStyle}>{title}</h2>
      <p style={panelSubtitleStyle}>{subtitle}</p>
      {children}
    </section>
  )
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: 'KZT',
    maximumFractionDigits: 0,
  }).format(Number(value || 0))
}

const pageStyle: React.CSSProperties = {
  padding: '32px',
  maxWidth: '1440px',
  margin: '0 auto',
  fontFamily: 'Inter, system-ui, sans-serif',
  background: '#f8fafc',
  minHeight: '100vh',
}

const headerRowStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'flex-start',
  gap: '16px',
  marginBottom: '24px',
}

const pageTitle: React.CSSProperties = {
  fontSize: '32px',
  fontWeight: 800,
  margin: 0,
  color: '#0f172a',
}

const mutedText: React.CSSProperties = {
  color: '#64748b',
  marginTop: '8px',
  marginBottom: 0,
}

const filtersWrapStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
  gap: '16px',
  marginBottom: '24px',
}

const filterBlockStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: '8px',
}

const labelStyle: React.CSSProperties = {
  fontSize: '14px',
  fontWeight: 600,
  color: '#334155',
}

const inputStyle: React.CSSProperties = {
  height: '44px',
  borderRadius: '12px',
  border: '1px solid #cbd5e1',
  padding: '0 14px',
  fontSize: '14px',
  background: '#fff',
  color: '#0f172a',
  outline: 'none',
}

const statsGridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
  gap: '16px',
  marginBottom: '24px',
}

const statCardStyle: React.CSSProperties = {
  background: '#fff',
  border: '1px solid #e2e8f0',
  borderRadius: '18px',
  padding: '20px',
  boxShadow: '0 1px 2px rgba(15, 23, 42, 0.04)',
}

const statTitleStyle: React.CSSProperties = {
  color: '#64748b',
  fontSize: '14px',
  marginBottom: '8px',
}

const statValueStyle: React.CSSProperties = {
  color: '#0f172a',
  fontSize: '28px',
  fontWeight: 800,
}

const twoColGridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))',
  gap: '16px',
  marginBottom: '24px',
}

const panelStyle: React.CSSProperties = {
  background: '#fff',
  border: '1px solid #e2e8f0',
  borderRadius: '20px',
  padding: '20px',
  boxShadow: '0 1px 2px rgba(15, 23, 42, 0.04)',
}

const panelTitleStyle: React.CSSProperties = {
  fontSize: '20px',
  fontWeight: 700,
  margin: '0 0 6px 0',
  color: '#0f172a',
}

const panelSubtitleStyle: React.CSSProperties = {
  margin: '0 0 16px 0',
  color: '#64748b',
  fontSize: '14px',
}

const tableWrapStyle: React.CSSProperties = {
  maxHeight: '420px',
  overflow: 'auto',
  border: '1px solid #e2e8f0',
  borderRadius: '14px',
}

const tableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  background: '#fff',
  fontSize: '14px',
}

const theadRowStyle: React.CSSProperties = {
  background: '#f8fafc',
  position: 'sticky',
  top: 0,
  zIndex: 1,
}

const thStyle: React.CSSProperties = {
  padding: '12px 14px',
  textAlign: 'left',
  borderBottom: '1px solid #e2e8f0',
  color: '#334155',
  fontWeight: 700,
}

const thStyleRight: React.CSSProperties = {
  ...thStyle,
  textAlign: 'right',
}

const tdStyle: React.CSSProperties = {
  padding: '12px 14px',
  borderBottom: '1px solid #f1f5f9',
  color: '#0f172a',
}

const tdStyleRight: React.CSSProperties = {
  ...tdStyle,
  textAlign: 'right',
}

const errorBoxStyle: React.CSSProperties = {
  background: '#fef2f2',
  color: '#991b1b',
  border: '1px solid #fecaca',
  padding: '16px',
  borderRadius: '12px',
}