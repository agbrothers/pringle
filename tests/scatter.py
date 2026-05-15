# ---------------------- Expressions ----------------------

### This should automatically create a scatter plot of d
d

### This should automatically create a scatter plot of d_rand
d_rand

### Plot a surface parametrized by a point created in data
equation_block:
    z = dot([x,y], d[2])


# ---------------------- Data ----------------------

### Define the data 
d = array([[0,1], [1,0], [-1, -1]])


### Here random is directly imported from np.random
d_rand = random((4, 2))
