/* Firmware for Hello World
 * Generate component-aware code from the Workbench tab.
 */
#include "stm32f1xx_hal.h"

UART_HandleTypeDef huart1;

void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_USART1_UART_Init(void);

int main(void) {
    HAL_Init();
    SystemClock_Config();
    MX_GPIO_Init();
    MX_USART1_UART_Init();

    uint8_t helloWorld[] = "Hello World\r\n";
    uint32_t tickCounter = 0;

    while (1) {
        if (tickCounter >= 100) {
            HAL_UART_Transmit(&huart1, helloWorld, sizeof(helloWorld) - 1, HAL_MAX_DELAY);
            tickCounter = 0;
        }
        HAL_IncTick();
        tickCounter++;
        HAL_Delay(1); // Delay to ensure the tick counter increments correctly
    }
}

void SystemClock_Config(void) {
    // System Clock Configuration
}

static void MX_GPIO_Init(void) {
    // GPIO Initialization
}

static void MX_USART1_UART_Init(void) {
    huart1.Instance = USART1;
    huart1.Init.BaudRate = 115200;
    huart1.Init.WordLength = UART_WORDLENGTH_8B;
    huart1.Init.StopBits = UART_STOPBITS_1;
    huart1.Init.Parity = UART_PARITY_NONE;
    huart1.Init.Mode = UART_MODE_TX_RX;
    huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    huart1.Init.OverSampling = UART_OVERSAMPLING_16;
    if (HAL_UART_Init(&huart1) != HAL_OK) {
        // Initialization Error
        Error_Handler();
    }
}

void Error_Handler(void) {
    // User can add his own implementation to report the HAL error return state
    while(1) {
    }
}

void SysTick_Handler(void) {
    HAL_IncTick();
}
