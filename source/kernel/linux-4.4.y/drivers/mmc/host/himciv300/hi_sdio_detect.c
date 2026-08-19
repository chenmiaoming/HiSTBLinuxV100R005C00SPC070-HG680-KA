/*
 * FiberHome HG-680-KA SDIO power/card-detect helper.
 *
 * The stock Android image uses a small hi_sdio_detect.ko module before the
 * MT7668 WLAN driver.  Static analysis of that module and the HiSilicon Wi-Fi
 * platform glue in this SDK agree on the board wiring:
 *
 *   WLAN_REG_ON = GPIO4_3 (global GPIO35)
 *   SDIO1 card-present control = bit 0 of physical register 0xf8a20008
 *
 * The stock 32-bit kernel accesses that physical register through the static
 * IO mapping __io_address(0xf8a20008) == 0xf9a20008.  This driver uses
 * of_iomap(), so its DT reg value must remain the physical 0xf8a20008 value.
 *
 * Phase A keeps this helper separate from the actual MT7668 driver.  Loading
 * hi_sdio_detect.ko powers the module and asserts card-present so that the MMC
 * core can enumerate the SDIO function.  Unloading it reverses the sequence.
 */

#include <linux/bitops.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/io.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_address.h>
#include <linux/platform_device.h>
#include <linux/slab.h>

#define HG680KA_SDIO_CARD_PRESENT	BIT(0)
#define HG680KA_POWER_SETTLE_MS		100
#define HG680KA_DETECT_SETTLE_MS	100

struct hg680ka_sdio_detect {
	struct gpio_desc *wlan_reg_on;
	void __iomem *card_detect_reg;
};

static void hg680ka_set_card_present(struct hg680ka_sdio_detect *priv,
				    bool present)
{
	u32 value;

	value = readl(priv->card_detect_reg);
	if (present)
		value |= HG680KA_SDIO_CARD_PRESENT;
	else
		value &= ~HG680KA_SDIO_CARD_PRESENT;
	writel(value, priv->card_detect_reg);

	/* Flush the posted write before changing power or returning. */
	readl(priv->card_detect_reg);
}

static int hg680ka_sdio_detect_probe(struct platform_device *pdev)
{
	struct hg680ka_sdio_detect *priv;
	u32 card_detect_ctrl;

	priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;

	priv->wlan_reg_on = devm_gpiod_get(&pdev->dev, "wlan-reg-on",
					   GPIOD_OUT_LOW);
	if (IS_ERR(priv->wlan_reg_on)) {
		dev_err(&pdev->dev, "failed to acquire WLAN_REG_ON GPIO: %ld\n",
			PTR_ERR(priv->wlan_reg_on));
		return PTR_ERR(priv->wlan_reg_on);
	}

	/*
	 * of_iomap() consumes the physical DT address.  The same register is
	 * referred to as 0xf9a20008 in stock ARM32 disassembly only because the
	 * MV310 static IO mapping adds 0x01000000 to physical 0xf8a20008.
	 */
	priv->card_detect_reg = of_iomap(pdev->dev.of_node, 0);
	if (!priv->card_detect_reg) {
		dev_err(&pdev->dev, "failed to map SDIO card-detect register\n");
		return -ENOMEM;
	}

	platform_set_drvdata(pdev, priv);

	/* Reproduce the stock helper's reset/power settling interval. */
	msleep(HG680KA_POWER_SETTLE_MS);
	gpiod_set_value_cansleep(priv->wlan_reg_on, 1);
	msleep(HG680KA_POWER_SETTLE_MS);

	hg680ka_set_card_present(priv, true);
	card_detect_ctrl = readl(priv->card_detect_reg);
	msleep(HG680KA_DETECT_SETTLE_MS);

	dev_info(&pdev->dev,
		 "WLAN_REG_ON high; SDIO1 card-present asserted, ctrl=0x%08x (expect MT7668 037a:7608)\n",
		 card_detect_ctrl);

	return 0;
}

static int hg680ka_sdio_detect_remove(struct platform_device *pdev)
{
	struct hg680ka_sdio_detect *priv = platform_get_drvdata(pdev);

	if (!priv)
		return 0;

	hg680ka_set_card_present(priv, false);
	msleep(HG680KA_DETECT_SETTLE_MS);
	gpiod_set_value_cansleep(priv->wlan_reg_on, 0);
	msleep(HG680KA_POWER_SETTLE_MS);

	if (priv->card_detect_reg) {
		iounmap(priv->card_detect_reg);
		priv->card_detect_reg = NULL;
	}

	dev_info(&pdev->dev, "SDIO1 card-present cleared; WLAN_REG_ON low\n");
	return 0;
}

static const struct of_device_id hg680ka_sdio_detect_of_match[] = {
	{ .compatible = "fiberhome,hg680-ka-sdio-power" },
	{ }
};
MODULE_DEVICE_TABLE(of, hg680ka_sdio_detect_of_match);

static struct platform_driver hg680ka_sdio_detect_driver = {
	.probe = hg680ka_sdio_detect_probe,
	.remove = hg680ka_sdio_detect_remove,
	.driver = {
		.name = "hg680ka-sdio-detect",
		.of_match_table = hg680ka_sdio_detect_of_match,
	},
};
module_platform_driver(hg680ka_sdio_detect_driver);

MODULE_AUTHOR("HG-680-KA Linux bring-up");
MODULE_DESCRIPTION("FiberHome HG-680-KA SDIO power/card-detect helper");
MODULE_LICENSE("GPL v2");
