import matplotlib.pyplot as plt
import numpy as np

min_el = 0
max_el = 180


# check real az/el
# chack gradient

# feel like with the right range for az/el the special operation could just be negation?

az, el = np.meshgrid(np.linspace(-180, 180, 90), np.linspace(-90, 90, 45))
raz = np.where(el < 0, (az + 360) % 360 - 180, az)
rel = np.where(el < 0, -el, el)


fig, ax = plt.subplots()
ax.quiver(az, el, raz, rel)
plt.show()
