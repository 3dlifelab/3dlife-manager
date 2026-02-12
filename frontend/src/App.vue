<template>
  <v-app style="max-width: none; overflow-x: hidden;">
     <v-layout>
    <v-app-bar color="primary" dark>
      <v-app-bar-title>3DL!FE</v-app-bar-title>

      <!-- Правая сторона шапки: статус подключения -->
      <div class="text-end mx-2" style="white-space: nowrap;">
        <div v-if="currentConnection" class="text-caption">
          <strong>{{ currentConnection.ssid }}</strong><br>
          <span>{{ currentConnection.ip }}</span>
        </div>
        <div v-else class="text-caption">
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

            <template v-slot:item.ssid="{ item }">
            <div class="d-flex align-center">
              <span class="font-weight-medium">
                <div :class="item.connected ? 'connected-cell font-weight-bold' : ''">
                  {{ item.ssid }}
                </div>
              </span>
              <v-icon
                v-if="item.known"
                size="x-small"
                color="blue"
                class="ms-1"
                icon="mdi-heart"
              ></v-icon>
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
          <template v-slot:item.secured="{ item }">
            <div :class="item.connected ? 'connected-cell' : ''">
              <v-chip
                :color="getChipColor(item)"
                size="small"
                :variant="item.connected ? 'flat' : 'outlined'"
              >
                {{ getStatusText(item) }}
              </v-chip>
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
const API_BASE = 'http://0.0.0.0:5001;' // Flask слушает порт 5001
// === Моковые данные ===


// === Состояние ===
const networks = ref([]);
const totalNetworks = ref(0);
const loading = ref(false);
const search = ref('');
const dialog = ref(false);
const password = ref('');
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

// === Методы ===
const loadConnectionStatus = async () => {
  try {
    const res = await fetch(`${API_BASE}/wifi/status`);
    if (!res.ok) throw new Error('Не удалось загрузить статус');

    const data = await res.json();

    // === Обновляем currentConnection с реальным IP ===
    if (data.name) {
      currentConnection.value = {
        ssid: data.name,
        ip: data.ip_address || '—', // реальный IP от NetworkManager
      };

      // === Обновляем connected-статус в списке сетей ===
      networks.value.forEach(network => {
        network.connected = (network.ssid === data.name);
      });
    } else {
      currentConnection.value = null;
      networks.value.forEach(n => { n.connected = false; });
    }
  } catch (err) {
    console.warn('Ошибка при обновлении статуса:', err);
    currentConnection.value = null;
    networks.value.forEach(n => { n.connected = false; });
  }
};
const refreshNetworks = async () => {
  loading.value = true;

  try {
    // 1. Запускаем сканирование
    await fetch(`${API_BASE}/wifi/rescan`, { method: 'POST' });
    
    // 2. Ждём 1.5 секунды — время на сканирование
    setTimeout(async () => {
      try {
        // 3. Получаем обновлённый список сетей
        const res = await fetch(`${API_BASE}/wifi/networks`);
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
        const res = await fetch(`${API_BASE}/wifi/networks`);
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
        showMessage('Не удалось загрузить даже без сканирования', 'error');
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

const forgetNetwork = async (ssid) => {
  try {
    const res = await fetch(`${API_BASE}/wifi/network/${encodeURIComponent(ssid)}`, {
      method: 'DELETE',
    });

    if (!res.ok) throw new Error('Не удалось удалить сеть');

    const result = await res.json();
    showMessage(`Сеть "${result.ssid}" забыта`, 'info');

    // Обновляем локальный список: помечаем как not known
    const net = networks.value.find(n => n.ssid === ssid);
    if (net) {
      net.known = false;
      net.secured = false; // опционально: если хочется обнулить
    }

    // Перезагружаем статус на всякий случай
    loadConnectionStatus();

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
  console.log('getRowClass:', item.ssid, 'connected:', item.connected);
  return item.connected ? 'connected-network-row' : '';
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

  if (net.connected) {
    // === Отключение ===
    try {
      const res = await fetch(`${API_BASE}/wifi/disconnect`, { method: 'POST' });
      if (!res.ok) throw new Error('Ошибка отключения');

      // Обновляем состояние
      networks.value.forEach(n => {
        if (n.ssid === net.ssid) n.connected = false;
      });
      currentConnection.value = null;
      showMessage(`Отключено от ${net.ssid}`, 'info');
    } catch (err) {
      showMessage(`Ошибка: ${err.message}`, 'error');
    }
  } else {
    // === Подключение ===
    if (net.secured && !net.known && !password.value) {
      // Только если сеть защищена, НО не сохранена (не known), И нет пароля — тогда ошибка
      showMessage('Введите пароль для новой сети!', 'warning');
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/wifi/connect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ssid: net.ssid,
          password: password.value || ''  // может быть пустым, если сеть known
        })
      });

      const result = await res.json();

      if (res.ok) {
        // Успешно начато подключение
        networks.value.forEach(n => {
          n.connected = n.ssid === net.ssid;
        });

        // Обновим статус подключения (включая IP)
        setTimeout(loadConnectionStatus, 1000);

        const msg = net.known
          ? `Подключаюсь к сохранённой сети: ${net.ssid}`
          : `Подключение к новой сети: ${net.ssid}`;
        showMessage(msg, 'success');
      } else {
        throw new Error(result.message || 'Не удалось подключиться');
      }
    } catch (err) {
      showMessage(`Ошибка: ${err.message}`, 'error');
    }
  }

  // Закрываем диалог
  dialog.value = false;

  // Сбрасываем пароль только если не планируем повторное использование
  if (net.secured && !net.known) {
    password.value = ''; // очищаем для безопасности
  }
  // Если known — можно оставить, но обычно не нужно
};

const showMessage = (msg, color = 'success') => {
  snackbar.message = msg;
  snackbar.color = color;
  snackbar.show = true;
};

const currentConnection = ref(null); // { ssid: '...', ip: '...' }


 

// Загрузка при старте
watch(
  () => networks.value,
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
</style>