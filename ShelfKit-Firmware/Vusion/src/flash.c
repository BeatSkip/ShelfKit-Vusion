/**
 * @file flash.c
 * @brief Minimal SPI NOR flash driver (25-series command set)
 */

#include "flash.h"
#include "spi.h"

#define CMD_READ        0x03    /* read data, 3-byte address */
#define CMD_JEDEC_ID    0x9F    /* read JEDEC ID */
#define CMD_RELEASE_PD  0xAB    /* release from deep power-down */
#define CMD_WREN        0x06    /* write enable */
#define CMD_PP          0x02    /* page program, 3-byte address */
#define CMD_SE          0x20    /* erase 4 KiB sector, 3-byte address */
#define CMD_RDSR        0x05    /* read status register */

#define FLASH_PAGE      256     /* page-program granularity */
#define FLASH_SECTOR    4096    /* sector-erase granularity */

void extflash_release_powerdown(void)
{
    spi_select(SPI_DEV_FLASH);
    spi_transfer(CMD_RELEASE_PD);
    spi_deselect(SPI_DEV_FLASH);
}

void extflash_read_jedec_id(uint8_t id[3])
{
    spi_select(SPI_DEV_FLASH);
    spi_transfer(CMD_JEDEC_ID);
    id[0] = spi_transfer(0x00);
    id[1] = spi_transfer(0x00);
    id[2] = spi_transfer(0x00);
    spi_deselect(SPI_DEV_FLASH);
}

void extflash_read(uint32_t addr, uint8_t *buf, uint16_t len)
{
    spi_select(SPI_DEV_FLASH);
    spi_transfer(CMD_READ);
    spi_transfer((uint8_t)(addr >> 16));
    spi_transfer((uint8_t)(addr >> 8));
    spi_transfer((uint8_t)addr);
    spi_read(buf, len);             /* clocks len bytes out of the chip */
    spi_deselect(SPI_DEV_FLASH);
}

#define FLASH_READY_POLLS   500     /* x delay(1000) ~= 0.5 s: a sector erase is ~0.1 s */

uint8_t extflash_wait_ready(void) __reentrant
{
    uint16_t n = FLASH_READY_POLLS;
    uint8_t status;

    for (;;) {
        spi_select(SPI_DEV_FLASH);
        spi_transfer(CMD_RDSR);
        status = spi_transfer(0x00);
        spi_deselect(SPI_DEV_FLASH);
        if (!(status & 0x01))       /* bit 0 = write/erase in progress */
            return 1;
        if (!--n)
            return 0;               /* never hang the tag on a dead SPI bus */
        delay(1000);
    }
}

static void flash_write_enable(void)
{
    spi_select(SPI_DEV_FLASH);
    spi_transfer(CMD_WREN);
    spi_deselect(SPI_DEV_FLASH);
}

uint8_t extflash_write(uint32_t addr, const uint8_t *buf, uint16_t len) __reentrant
{
    while (len) {
        uint16_t room = (uint16_t)(FLASH_PAGE - (addr & (FLASH_PAGE - 1)));
        uint16_t n = (len < room) ? len : room;

        if (!extflash_wait_ready())
            return 0;
        flash_write_enable();
        spi_select(SPI_DEV_FLASH);
        spi_transfer(CMD_PP);
        spi_transfer((uint8_t)(addr >> 16));
        spi_transfer((uint8_t)(addr >> 8));
        spi_transfer((uint8_t)addr);
        spi_write(buf, n);
        spi_deselect(SPI_DEV_FLASH);

        addr += n;
        buf += n;
        len -= n;
    }
    return extflash_wait_ready();
}

uint8_t extflash_erase(uint32_t addr, uint16_t len) __reentrant
{
    while (len) {
        if (!extflash_wait_ready())
            return 0;
        flash_write_enable();
        spi_select(SPI_DEV_FLASH);
        spi_transfer(CMD_SE);
        spi_transfer((uint8_t)(addr >> 16));
        spi_transfer((uint8_t)(addr >> 8));
        spi_transfer((uint8_t)addr);
        spi_deselect(SPI_DEV_FLASH);

        addr += FLASH_SECTOR;
        len = (len > FLASH_SECTOR) ? (uint16_t)(len - FLASH_SECTOR) : 0;
    }
    return extflash_wait_ready();
}
