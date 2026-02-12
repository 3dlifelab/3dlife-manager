<template>
  <v-app>
    <v-app-bar color="primary" dark>
      <v-app-bar-title>Wi-Fi Manager</v-app-bar-title>
      <v-spacer></v-spacer>
      <title>test</title>
      <v-btn icon @click="refreshNetworks">
        <v-icon>mdi-refresh</v-icon>
      </v-btn>
    </v-app-bar>

    <v-main class="pa-6">
      <v-card elevation="2" rounded="lg">
        <v-card-title>
          Доступные Wi-Fi сети
          <v-spacer></v-spacer>
          <v-text-field
            v-model="search"
            append-icon="mdi-magnify"
            label="Поиск"
            single-line
            hide-details
            density="compact"
            style="max-width: 300px"
          ></v-text-field>
        </v-card-title>

        <v-data-table-server
          :items="networks"
          :headers="headers"
          :items-length="totalNetworks"
          :loading="loading"
          :search="search"
          item-value="ssid"
        >
          <template v-slot:item.strength="{ item }">
            <v-rating
              :model-value="getSignalStrength(item.raw.strength)"
              readonly
              half-increments
              size="small"
              density="compact"
              background-color="amber lighten-3"
              color="amber"
            ></v-rating>
          </template>

          <template v-slot:item.secured="{ item }">
            <v-chip
              :color="item.raw.secured ? 'warning' : 'success'"
              size="small"
              variant="outlined"
            >
              {{ item.raw.secured ? 'Защищена' : 'Открыта' }}
            </v-chip>
          </template>

          <template v-slot:item.actions="{ item }">
            <v-btn
              size="small"
              color="primary"
              variant="text"
              @click="openConnectDialog(item.raw)"
            >
              {{ item.raw.connected ? 'Отключиться' : 'Подключиться' }}
            </v-btn>
          </template>
        </v-data-table-server>
      </v-card>
    </v-main>

    <!-- Диалог подключения -->
    <v-dialog v-model="dialog" max-width="500px">
      <v-card>
        <v-card-title class="text-h6">
          {{ currentNetwork.connected ? 'Отключиться от сети' : 'Подключиться к сети' }}
        </v-card-title>

        <v-card-text class="pt-4">
          <div v-if="!currentNetwork.connected && currentNetwork.secured">
            <p>Введите пароль для сети <strong>{{ currentNetwork.ssid }}</strong></p>
            <v-text-field
              v-model="password"
              label="Пароль"
              type="password"
              variant="outlined"
              hide-details
            ></v-text-field>
          </div>

          <div v-else>
            Вы уверены, что хотите {{ currentNetwork.connected ? 'отключиться от' : 'подключиться к' }} сети <strong>{{ currentNetwork.ssid }}</strong>?
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
  </v-app>
</template>

<script setup>
import { ref, reactive } from 'vue';

// === Моковые данные ===
const generateMockNetworks = () => [
  { ssid: 'HomeNetwork', strength: 4, secured: true, connected: false },
  { ssid: 'Guest-WiFi', strength: 3, secured: false, connected: false },
  { ssid: 'OfficeSecure', strength: 5, secured: true, connected: false },
  { ssid: 'Starbucks_WiFi', strength: 2, secured: false, connected: false },
  { ssid: 'MyRouter', strength: 5, secured: true, connected: true },
  { ssid: 'NeighbourNet', strength: 1, secured: true, connected: false },
];

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
  { title: 'Действия', key: 'actions', sortable: false },
];

// === Методы ===
const refreshNetworks = () => {
  loading.value = true;
  // Имитация задержки загрузки
  setTimeout(() => {
    const mockData = generateMockNetworks();
    networks.value = mockData;
    totalNetworks.value = mockData.length;
    loading.value = false;
  }, 800);
};

const getSignalStrength = (strength) => {
  return strength / 5; // преобразуем в 0-1 для рейтинга из 5 звёзд
};

const openConnectDialog = (network) => {
  currentNetwork.value = { ...network };
  password.value = '';
  dialog.value = true;
};

const confirmAction = () => {
  const net = currentNetwork.value;

  if (net.connected) {
    // Отключение
    showMessage(`Отключено от ${net.ssid}`, 'info');
    const index = networks.value.findIndex(n => n.ssid === net.ssid);
    if (index !== -1) networks.value[index].connected = false;
  } else if (net.secured && !password.value) {
    showMessage('Введите пароль!', 'error');
    return;
  } else {
    // Подключение
    showMessage(`Подключено к ${net.ssid}`, 'success');
    const index = networks.value.findIndex(n => n.ssid === net.ssid);
    if (index !== -1) {
      networks.value[index].connected = true;
      // Сбрасываем подключения у других
      networks.value.forEach((n, i) => {
        if (i !== index) n.connected = false;
      });
    }
  }

  dialog.value = false;
};

const showMessage = (msg, color = 'success') => {
  snackbar.message = msg;
  snackbar.color = color;
  snackbar.show = true;
};

// Загрузка при старте
refreshNetworks();
</script>

<style scoped>
.v-app-bar-title {
  font-size: 1.2rem;
  font-weight: 500;
}
</style>