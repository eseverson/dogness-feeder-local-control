#!/bin/sh
# check_ir_gpio.sh — snapshot sysfs state for the GPIOs majestic toggles
# on day/night transitions. Run before and after triggering a transition;
# diff the output to confirm whether the kernel sees majestic's writes.
#
#   IR LED:  gpio0   (group 0, pin 0)
#   IR cut:  gpio37  (group 4, pin 5)

for g in 0 37; do
	d=/sys/class/gpio/gpio$g
	if [ ! -d "$d" ]; then
		echo "gpio$g: not exported"
		continue
	fi
	dir=$(cat "$d/direction" 2>/dev/null)
	val=$(cat "$d/value"     2>/dev/null)
	echo "gpio$g: direction=$dir value=$val"
done

echo "ts=$(date +%s) ($(date))"
