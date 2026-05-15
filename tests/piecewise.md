# ---------------------- Expressions ----------------------


"""A cell with a string should be treated as a comment/note. 
   The following block provides an example for a piecewise 
   function implementation."""


### Plot the multiple piecewise surface
### This should validate that the number of conditions equals
### the number of pieces. Later conditions should implicitly
### assume prior conditions are false
z = {f, g, h}
    condition: x**2 + y**2 < 1
    condition: x**2 + y**2 < 2 
    condition: x**2 + y**2 >= 2
### For the second condition above, we might want to assume prior 
### the prior condition is negated `and not x**2 + y**2 < 1` to 
### prevent cases where conditions from more than one piece may 
### be true simultaneously, leading to conflict between what should
### be active.  

f(x,y) =  x**2 + y**2


g(x,y) = -x**2 - y**2


h(x,y) = 2*x**2 + 2*y**2


# ---------------------- Data ----------------------


