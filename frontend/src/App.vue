<template>
  <v-app style="max-width: none; overflow-x: hidden;">
     <v-layout>
    <v-app-bar color="primary" dark>
      <v-app-bar-title>3DL!FE</v-app-bar-title>

      <!-- Правая сторона шапки: статус подключения -->
    <div class="text-end mx-2" style="white-space: nowrap;">
      <div v-if="activeConnection" class="text-caption">
        <!-- Иконка типа подключения -->
        <v-icon size="small" class="me-1">
          {{ activeConnection.type === 'ethernet' ? 'mdi-ethernet' : 'mdi-wifi' }}
        </v-icon>
        
        <!-- Название и IP -->
        <strong>{{ activeConnection.name }}</strong><br>
        <span class="text-medium-emphasis">{{ activeConnection.ip }}</span>
      </div>
      
      <div v-else class="text-caption text-medium-emphasis">
        <v-icon size="small" class="me-1">mdi-wifi-off</v-icon>
        Не подключено
      </div>
    </div>

      <!-- Кнопка обновить -->
      <v-btn icon @click="refreshNetworks">
        <v-icon>mdi-refresh</v-icon>
      </v-btn>
    </v-app-bar>
      <v-main class="pa-0 ma-0" style="min-height: 100vh; padding-top: 64px;">      
        <v-card elevation="2" rounded="lg" class="w-100 h-100" flat>
        <!-- Заголовок без поиска -->
          <!-- Всё, больше ничего справа не нужно -->


        <v-data-table
          :items="networks"
          :headers="headers"
          :items-length="totalNetworks"
          :loading="loading"
          :search="search"
          :item-class="getRowClass"
          @click:row="onRowClick" 
          item-value="ssid"
          style="width: 100%; max-width: 100%; padding-top: 64px;"
          hover>

          <template v-slot:item.secured="{ item }">
            <div :class="item.connected ? 'connected-cell' : ''">
              <!-- Индикатор подключения -->
              <div v-if="connectingSsid === item.ssid" class="connecting-indicator">
                <v-progress-circular
                  size="16"
                  width="2"
                  color="primary"
                  indeterminate
                  class="me-2"
                ></v-progress-circular>
                <span class="text-caption">Подключение...</span>
              </div>
              
              <!-- Обычный статус -->
              <v-chip
                v-else
                :color="getChipColor(item)"
                size="small"
                :variant="item.connected ? 'flat' : 'outlined'"
              >
                {{ getStatusText(item) }}
              </v-chip>
            </div>
          </template>
          <template v-slot:item.strength="{ item }">
            <div class="signal-bar-container">
              <div
                class="signal-bar"
                :style="{
                  width: `${item.strength * 20}%`,
                  backgroundColor: getSignalColor(item.strength)
                }"
              ></div>
            </div>
          </template>
          <template v-slot:item.actions="{ item }">
  <div class="d-flex gap-1">
    <!-- Кнопка "Забыть" — только для known-сетей -->
    <v-tooltip text="Удалить из сохранённых">
      <template v-slot:activator="{ props }">
        <v-btn
          v-if="item.known"
          v-bind="props"
          icon
          size="large"
          color="error"
          variant="text"
          @click.stop="forgetNetwork(item.ssid)"
        >
          <v-icon size="small">mdi-delete</v-icon>
        </v-btn>
      </template>
    </v-tooltip>

    <!-- Опционально: можно оставить "Подключиться" как действие -->
  </div>
</template>

          <!-- <template v-slot:item.actions="{ item }">
            <v-btn
              size="small"
              color="primary"
              variant="text"
              @click="openConnectDialog(item)"
            >
              {{ item.connected ? 'Отключиться' : 'Подключиться' }}
            </v-btn>
          </template> -->
        </v-data-table>
      </v-card>
    </v-main>

    <!-- Диалог подключения -->
    <v-dialog v-model="dialog" max-width="500px">
      <v-card>
        <v-card-title class="text-h6">
          {{ currentNetwork.connected ? 'Отключение от сети' : 'Подключение к сети' }}
        </v-card-title>

        <v-card-text class="pt-4">
          <div v-if="!currentNetwork.connected && currentNetwork.secured && !currentNetwork.known">
            <p>Введите пароль для сети <strong>{{ currentNetwork.ssid }}</strong></p>
            <v-text-field
              v-model="password"
              label="Пароль"
              type="password"
              variant="outlined"
              hide-details
              class="mt-4"
            ></v-text-field>
          </div>

          <div v-else>
            {{ currentNetwork.connected
              ? `Вы уверены, что хотите отключиться от "${currentNetwork.ssid}"?`
              : currentNetwork.known
                ? `Подключиться к сохранённой сети "${currentNetwork.ssid}"?`
                : `Подключиться к новой сети "${currentNetwork.ssid}"?`
            }}
          </div>
        </v-card-text>

        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn color="secondary" variant="text" @click="dialog = false">Отмена</v-btn>
          <v-btn color="primary" @click="confirmAction">Подтвердить</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Уведомление -->
    <v-snackbar v-model="snackbar.show" :timeout="3000" :color="snackbar.color">
      {{ snackbar.message }}
    </v-snackbar>
    </v-layout>
  </v-app>
</template>

<script setup>
import { ref, reactive } from 'vue';
const API_BASE = 'http://localhost:5001' // Flask слушает порт 5001
// === Моковые данные ===


// === Состояние ===
const networks = ref([]);
const totalNetworks = ref(0);
const loading = ref(false);
const search = ref('');
const connectingSsid = ref(null); // SSID сети, к которой идёт подключение
const connectionStartTime = ref(null); // Для анимации прогресса
const dialog = ref(false);
const password = ref('');
const activeConnection = ref(null); // { type: 'ethernet'|'wifi', name: '...', ip: '...' }
const wifiStatus = ref(null);       // Детальный статус Wi-Fi
const ethernetStatus = ref(null);   // Детальный статус Ethernet
const snackbar = reactive({
  show: false,
  message: '',
  color: 'success',
});
const currentNetwork = ref({});

// === Заголовки таблицы ===
const headers = [
  { title: 'SSID', key: 'ssid', sortable: true },
  { title: 'Сигнал', key: 'strength', sortable: true },
  { title: 'Статус', key: 'secured', sortable: true },
  { title: 'Действия', key: 'actions', sortable: false }
  // { title: 'Действия', key: 'actions', sortable: false },
];

// === Методы ===1
const loadConnectionStatus = async () => {
  try {
    const res = await fetch(`/wifi/status`);
    if (!res.ok) throw new Error('Не удалось загрузить статус');

    const data = await res.json();

    // Сохраняем детальные статусы
    wifiStatus.value = data.wifi;
    ethernetStatus.value = data.ethernet;
    
    // Используем готовое активное соединение с бэкенда
    activeConnection.value = data.active_connection;

    // Синхронизируем статус подключения в списке сетей
    networks.value.forEach(network => {
      network.connected = (data.wifi.connected && network.ssid === data.wifi.ssid);
    });
    
  } catch (err) {
    console.warn('Ошибка при обновлении статуса:', err);
    activeConnection.value = null;
  }
};
const refreshNetworks = async () => {
  loading.value = true;
  connectingSsid.value = null; // ✅ Сброс индикатора при обновлении
  connectionStartTime.value = null;
  try {
    // 1. Запускаем сканирование
    await fetch(`wifi/rescan`, { method: 'POST' });
    
    // 2. Ждём 1.5 секунды — время на сканирование
    setTimeout(async () => {
      try {
        // 3. Получаем обновлённый список сетей
        const res = await fetch(`/wifi/networks`);
        if (!res.ok) throw new Error('Не удалось загрузить сети');
        
        const rawData = await res.json(); // Массив объектов

        // 4. Мапим в нужную структуру
        networks.value = rawData.map(net => ({
          ssid: net.SSID,
          bssid: net.BSSID,
          strength: Math.max(1, Math.min(5, Math.ceil(net.signal_level / 20))), // 0–100 → 1–5
          secured: Boolean(net.security), // если есть security — значит защищена
          known: Boolean(net.known),
          connected: false // будет обновлено позже через loadConnectionStatus
        }));

        totalNetworks.value = networks.value.length;

        // 5. Синхронизируем текущее подключение (SSID + IP + connected)
        await loadConnectionStatus();

      } catch (err) {
        console.error('Ошибка при загрузке сетей:', err);
        showMessage(`Ошибка: ${err.message}`, 'error');
        networks.value = [];
        currentConnection.value = null;
      } finally {
        loading.value = false;
      }
    }, 3000);

  } catch (err) {
    console.error('Ошибка запуска сканирования:', err);
    showMessage(`Не удалось запустить сканирование: ${err.message}`, 'warning');

    // На всякий случай — попробуем сразу получить сети без rescan
    setTimeout(async () => {
      try {
        const res = await fetch(`/wifi/networks`);
        const data = await res.json();
        networks.value = data.map(net => ({
          ssid: net.SSID,
          bssid: net.BSSID,
          strength: Math.max(1, Math.min(5, Math.ceil(net.signal_level / 20))),
          secured: Boolean(net.security),
          known: Boolean(net.known),
          connected: false
        }));
        totalNetworks.value = networks.value.length;
        await loadConnectionStatus();
      } catch (e) {
        showMessage('Не удалось загрузить', 'error');
        networks.value = [];
      } finally {
        loading.value = false;
      }
    }, 500);
  }
};
const getSignalStrength = (strength) => {
  return strength / 5; // преобразуем в 0-1 для рейтинга из 5 звёзд
};

// === Исправленная функция forgetNetwork ===
const forgetNetwork = async (ssid) => {
  try {
    const res = await fetch(`/wifi/network/${encodeURIComponent(ssid)}`, {
      method: 'DELETE',
    });

    if (!res.ok) throw new Error('Не удалось удалить сеть');

    const result = await res.json();
    showMessage(`Сеть "${result.ssid}" забыта`, 'info');

    // ❌ УДАЛЕНО: Не меняем net.secured и net.known вручную!
    // const net = networks.value.find(n => n.ssid === ssid);
    // if (net) {
    //   net.known = false;
    //   net.secured = false; // <-- ЭТО БЫЛО ПРИЧИНОЙ СТАТУСА "ОТКРЫТАЯ"
    // }

    // ✅ ПРАВИЛЬНО: Полностью перезагружаем список сетей
    // Это обновит known=false и сохранит правильный secured (WPA2/Open)
    await refreshNetworks(); 

  } catch (err) {
    showMessage(`Ошибка при удалении: ${err.message}`, 'error');
    console.error(err);
  }
};

const getStatusText = (item) => {
  if (item.connected) return 'Подключено';
  return item.secured ? 'Защищена' : 'Открыта';
};
const getSignalClass = (strength) => {
  // strength: 1–5
  return strength;
};

const getSignalColor = (strength) => {
  if (strength <= 2) return '#f44336';   // красный
  if (strength === 3) return '#ff9800';  // оранжевый
  if (strength === 4) return '#ffeb3b';  // жёлтый
  return '#4caf50';                       // зелёный
};
const getChipColor = (item) => {
  if (item.connected) return 'primary';
  return item.secured ? 'warning' : 'success';
};

const getRowClass = (item) => {
  if (item.connected) return 'connected-network-row';
  if (connectingSsid.value === item.ssid) return 'connecting-network-row';
  return '';
};

const openConnectDialog = (network) => {
  currentNetwork.value = { ...network };
  password.value = '';
  dialog.value = true;
};
const onRowClick = (event, item) => {
  // `item` — это { columns: { ssid, strength, ... }, item: оригинальный объект }
  openConnectDialog(item.item); // `item.item` — наш объект сети
};
const confirmAction = async () => {
  const net = currentNetwork.value;

  // Проверка пароля
  if (net.secured && !net.known && !password.value) {
    showMessage('Введите пароль для новой сети!', 'warning');
    return;
  }

  const ssid = net.ssid;
  const pass = password.value || '';
  const wasKnown = net.known;

  // ✅ Закрываем диалог сразу
  dialog.value = false;

  // ✅ Устанавливаем индикатор подключения
  connectingSsid.value = ssid;
  connectionStartTime.value = Date.now();

  if (net.connected) {
    // === Отключение ===
    try {
      const res = await fetch(`/wifi/disconnect`, { method: 'POST' });
      if (!res.ok) throw new Error('Ошибка отключения');

      showMessage(`Отключено от ${ssid}`, 'info');
    } catch (err) {
      showMessage(`Ошибка: ${err.message}`, 'error');
    } finally {
      connectingSsid.value = null;
      connectionStartTime.value = null;
      await refreshNetworks(); // ✅ Обновляем список
    }
  } else {
    // === Подключение ===
    try {
      const res = await fetch(`/wifi/connect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ssid: ssid,
          password: pass
        })
      });

      const result = await res.json();

      if (res.ok) {
        showMessage(`✅ Подключено к ${ssid}`, 'success');
      } else {
        showMessage(`❌ ${result.error || 'Не удалось подключиться'}`, 'error');
      }
    } catch (err) {
      showMessage(`❌ Ошибка: ${err.message}`, 'error');
    } finally {
      // ✅ Сбрасываем индикатор и обновляем список в любом случае
      connectingSsid.value = null;
      connectionStartTime.value = null;
      await refreshNetworks(); // ✅ Ключевое изменение
    }
  }

  // Сброс пароля
  if (net.secured && !net.known) {
    password.value = '';
  }
};



const showMessage = (msg, color = 'success') => {
  snackbar.message = msg;
  snackbar.color = color;
  snackbar.show = true;
};

const currentConnection = ref(null); // { ssid: '...', ip: '...' }


 

// Загрузка при старте
watch(

  () => {
    loadConnectionStatus();
  },
  { deep: true }
);

onMounted(() => {
  refreshNetworks(); // ✅ Вызывается при каждом монтировании компонента
});
</script>

<style>
.v-app-bar-title {
  font-size: 1.2rem;
  font-weight: 500;
}
.clickable-rows tbody tr {
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.clickable-rows tbody tr:hover {
  background-color: rgba(0, 0, 0, 0.04);
}

/* Опционально: при наведении — не терять выделение */

.connected-network-row {
  border-left: 4px solid #1976d2 !important; /* синяя полоса */
  background-color: #f5f9ff !important;     /* очень светлый фон */
  font-weight: 500;
  transition: all 0.2s ease;
}
.connected-network-row:hover {
  background-color: rgba(25, 118, 210, 0.15) !important;
}
.signal-bar-container {
  width: 60px;
  height: 6px;
  background-color: #e0e0e0;
  border-radius: 3px;
  overflow: hidden;
}

.signal-bar {
  height: 100%;
  border-radius: 3px;
  transition: background-color 0.2s, width 0.3s;
}

.connecting-indicator {
  display: flex;
  align-items: center;
  padding: 4px 8px;
  background-color: rgba(25, 118, 210, 0.08);
  border-radius: 4px;
  border: 1px dashed rgba(25, 118, 210, 0.3);
}

/* Пульсация для строки которая подключается */
.connecting-network-row {
  animation: pulse-row 2s ease-in-out infinite;
  background-color: rgba(25, 118, 210, 0.1) !important;
}

@keyframes pulse-row {
  0%, 100% {
    background-color: rgba(25, 118, 210, 0.08) !important;
  }
  50% {
    background-color: rgba(25, 118, 210, 0.15) !important;
  }
}
</style>
