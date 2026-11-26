<template>
  <v-container>
    <div class="d-flex flex-wrap align-center justify-space-between ga-3 mb-4">
      <div>
        <h1 class="text-h5">Wi-Fi менеджер</h1>
        <p v-if="status?.active_connection">
          {{ status.active_connection.name }} {{ status.active_connection.ip }}
        </p>
      </div>
      <v-btn :loading="busy" :disabled="busy || status?.wifi.enabled === false" @click="refresh(true)">
        Сканировать
      </v-btn>
    </div>

    <v-alert v-if="error" class="mb-4" type="error">{{ error }}</v-alert>
    <v-alert v-if="notice" class="mb-4" type="info">{{ notice }}</v-alert>
    <v-alert v-else-if="status?.wifi.enabled === false" class="mb-4" type="info">
      Wi-Fi выключен
    </v-alert>
    <v-text-field v-model="search" label="Поиск сети" prepend-inner-icon="mdi-magnify" />

    <v-data-table
      :headers="headers"
      :items="networks"
      :loading="busy"
      :search="search"
      item-value="BSSID"
      no-data-text="Сети не найдены"
    >
      <template #item.signal_level="{ item }">{{ item.signal_level }}%</template>
      <template #item.actions="{ item }">
        <v-btn size="small" variant="text" :disabled="busy" @click="selectNetwork(item)">
          {{ isConnected(item) ? 'Отключиться' : 'Подключиться' }}
        </v-btn>
      </template>
    </v-data-table>

    <v-dialog v-model="dialog" :persistent="busy" max-width="460">
      <v-card v-if="selected" :title="selected.SSID">
        <v-card-text v-if="requiresPassword || actionError">
          <v-alert v-if="actionError" class="mb-3" type="error">{{ actionError }}</v-alert>
          <v-text-field
            v-if="requiresPassword"
            v-model="password"
            :disabled="busy"
            label="Пароль Wi-Fi"
            type="password"
            @keyup.enter="confirmAction"
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn :disabled="busy" @click="dialog = false">Отмена</v-btn>
          <v-btn :disabled="busy || (requiresPassword && !password)" :loading="busy" @click="confirmAction">
            {{ isConnected(selected) ? 'Отключиться' : 'Подключиться' }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

interface WifiNetwork {
  SSID: string
  BSSID: string
  known: boolean
  security: string
  signal_level: number
}

interface WifiStatus {
  wifi: { enabled: boolean, connected: boolean, ssid: string | null }
  active_connection: { name: string, ip: string | null } | null
}

const headers = [
  { title: 'Сеть', key: 'SSID' },
  { title: 'Сигнал', key: 'signal_level' },
  { title: 'Защита', key: 'security' },
  { title: 'Действие', key: 'actions', sortable: false },
]

const networks = ref<WifiNetwork[]>([])
const status = ref<WifiStatus>()
const selected = ref<WifiNetwork>()
const search = ref('')
const password = ref('')
const busy = ref(false)
const dialog = ref(false)
const error = ref('')
const notice = ref('')
const actionError = ref('')
const requiresPassword = computed(() => {
  const network = selected.value
  return Boolean(network && !network.known && !isConnected(network)
    && !['Open', 'OWE', 'OWE-TM'].includes(network.security))
})

watch(dialog, open => {
  if (!open) password.value = ''
})

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch('/wifi/' + path, options)
  const data = await response.json().catch(() => null)
  if (!response.ok || data === null) {
    throw new Error(data?.message || data?.error || `Ошибка API Wi-Fi (HTTP ${response.status})`)
  }
  return data
}

async function loadNetworks() {
  const [wifiStatus, scannedNetworks] = await Promise.all([
    api<WifiStatus>('status'),
    api<WifiNetwork[]>('networks'),
  ])
  status.value = wifiStatus
  const strongestBySsid = new Map<string, WifiNetwork>()
  for (const network of scannedNetworks) {
    if (!strongestBySsid.has(network.SSID)) strongestBySsid.set(network.SSID, network)
  }
  networks.value = [...strongestBySsid.values()]
}

async function refresh(scan = false) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    if (scan) {
      const result = await api<{ status: string }>('rescan', { method: 'POST' })
      if (result.status === 'scan_started') {
        notice.value = 'Сканирование ещё выполняется. Показаны последние доступные результаты.'
      }
    }
    await loadNetworks()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    busy.value = false
  }
}

function isConnected(network: WifiNetwork) {
  return status.value?.wifi.connected && status.value.wifi.ssid === network.SSID
}

function selectNetwork(network: WifiNetwork) {
  selected.value = network
  password.value = ''
  actionError.value = ''
  dialog.value = true
}

async function confirmAction() {
  const network = selected.value
  if (!network || busy.value || (requiresPassword.value && !password.value)) return
  busy.value = true
  actionError.value = ''
  try {
    if (isConnected(network)) {
      await api('disconnect', { method: 'POST' })
    } else {
      await api('connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ssid: network.SSID, password: password.value }),
      })
    }
    dialog.value = false
    error.value = ''
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    busy.value = false
  }
  if (!dialog.value) await refresh()
}

onMounted(() => refresh())
</script>
