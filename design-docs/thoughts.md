Please update the design docs and add new ones as they make sense, including one for the panel architecture. You may want to wait to update those until getting through the following:

Regarding tradeoffs, I really like the per-cell run feature that desmos currently has to re-sample random data, and would like to incorporate the same feature. It would be rather chaotic to have the re-sampling automatically tied to other features. 

Regarding security, I think it would be reasonable to strictly support numpy and scipy functions only. It might be more concise to import functions directly from numpy so that the user doesn't need to prefix everything AND so that the number of things we evaluate is explicitly limited to what we directly import from those packages. For example:
```
from numpy import sin, cos, pi, random, array, ...
from numpy.linalg import norm, inv, ...

y = sin(x)
```
Hopefully that restriction prevents totally arbitrary code execution. How does that influence the eval/exec/ast considerations? This may also depend on multi-line equation choices. 

Can you review how ordering in desmos currently works? From my experience, ordering does not matter, so I'd be curious to hear how desmos determines execution order, if that is documented. Cells can be dragged around and re-organized into folders, and ordering has no bearing on execution. If an equation is written but a paramter is not defined, Desmos identifies this and provides a suggestion button to add that parameter. If you click on it, it automatically adds a definition for that parameter to a new cell with a default value and slider. It would be amazing if we could preserve both this suggestion behavior and the ability to drag and rearrange cells in the left panel, as well as add folders and comment cells for organization. 

We will also absolutely need shape validation, and want the cells to warn users rather than crashing the program. 


Regarding multi-line expressions, this is probably what I will want to do the most playing around with when we get to the mockup stage. It could be useful to have something like a constraint cell, and then under the hood, the function we plot is roughly compute and some a mask roughly like `np.where((*constraints))`, and plot the unmasked portion of the function. I also prefer the idea of having the first expression in a block to be the magic name with constraints and other items underneath. This is purely a visual/UI consideration, and doesn't need to govern the order in which cells are evaluated. 

While desmos doesn't support multi-line constraint definition, it implicitly supports multiline expressions by allowing one to define an equation like `f(x,y) = ...)` and `z = 2*f(x,y)`. This `f(x,y)` would probably be done most naturally with lambda functions. 

I also still want to be able to plot lines like `y = x`. So we probably also want those to be magic variable names if they are not in constraint fields. 

I also want to preserve the feature that allows plotted expressions to be toggle on and off, to allow the user to selectively visualize different expressions. This also enables the composition of multiple expressions without rendering all of the modular pieces. 


-------------------------------

Good updates. Does Desmos's dependency graph and parse time variable analysis approach seems ideal to keep. Does this work with our currently proposed approach? 

I've also added a tests directory with some rough ideas for initial tests and thoughts on cell organization. We probably want some kind of `+` button on an expression cell that lets the user add constraint subcells. Please review these tests and let me know if they conform to or contradict the way you were thinking about implementing things. It's very important the be on the same page about this before an initial implementation. 

We should also talk visual styling. Desmos allows the user to pop open a panel and control colors, line width, opacity, and other nice tools to customize the plot. Can you describe their implementation in more depth, and perhaps connect that to the implementation we are discussing here? Particularly, the practicality or implementation constraints we would face with your recommended UI tools (Vispy or pygfx/wgpu-py)?




-------------------------------

Good to hear regarding the variable analysis and dependency graph. Please update our docs to note this and update the desmos 3d overview to reflect the discussion about their visual styling implementation. We can create a new doc for our own visual styling choices. I would probably like to start with an identical interface from the user's perspective, a UI button to open a panel and select whatever styles. I don't think transparency is a critical feature, but it is a nice-to-have to keep in consideration. 

For the test file mockups, I should have been more clear that this was more an excercise in thinking out loud. Some of the invalid python is not necessarily something I want explicitly evaluated by our parser, but may be suggestive of UI elements conveying information to the user or providing structure to our parser. For instance, I would not have the user explicitly type `constraint: `. Rather, I was imagining the cell iteslf maybe had some text or visual indicator that it was a constraint cell. Then, perhaps, on the backend, we check that the equations in each constraint box in a block are valid and add them to a list of constraints, then evaluate them using `where` or `logical_and` or something similar to generate a mask or other constraint enforcing mechanism. 

So maybe behind the scenes it's something like
```
constraints = [
    x**2 + y**2 < 1,
    x < 0.5,
    x > -0.5,
    z > 0, 
]
```

My thoughts on constraints/masking are pretty half-baked here as well. I could benefit from further discussion and ideas here. I'm assuming the actual implementation of our surfaces is something like passing a vectorized meshgrid through it, probably in parallel on the GPU. Assuming that to be the case, a constraint like `x**2 + y**2 < 1` is applied to the meshgrid and can be used as a boolean mask to control which meshgrid cells contribute to our surface. For multiple constraints, one approach could be to create multiple separate masks, and them, and repeat the process. 1) is this valid with the implementation you were imagining, and 2) are there better or more efficient or otherwise more appropriate ways to do this? Does this capture all cases, like piecewise constraints and other equation level specifications that may be useful here?


Regarding the auto-plotting bare variables, I do think we should adopt this approach. Please document this decision, previous assumptions, and the rational behind it. 

For functions like `f(x,y)`, I think it would be nice to have our parser automatically identify convert those into lambda functions. Even though the raw code is invalid python, it's very close, easily converted, and makes things much more concise and readable. Please also document this decision and record the processing mockups you provided. Perhaps also add a new doc for the processing pipeline mockup that we can build on. 

For the unresolved question regarding 
```
z = p*f(x,y) + (1-p)*g(x,y)
f(x,y) =  x**2 + y**2
g(x,y) = -x**2 - y**2
```

I was envisioning each line here being different equation blocks, and I've updated surface.py to make that more clear. That should then fall under the arbitrary ordering paradigm that the desmos approach allows for. Please let me know if I am misunderstanding anything here. I was not imagining being able to define sub/modular equations within an existing equation's block. Equation blocks should probably only allow subcells for constraints, maybe functions describing color functions, and other equation-specific things. Does this track with your model? 


-------------------------------

Okay, I think we're on the same page so far. Regarding the Constraint sub-cell UI, that is exactly how I was envisioning it. The subcell should be inline below the primary, possibly with a dashed or colored border indicating that it is a constraint. We can discuss details when we get closer to the implementation stage. Cell creation probably happens by clicking on the parent expression cell and either a global `+` add button, or a local `+` button attached to the parent cell, and then selecting constraint from a dropdown of optional subcells. 

For the "Auto-plot shape inference for parametric surfaces" concern, I believe desmos allows the user to choose whether a (N, 3) shaped data is rendered as a scatterplot or a line plot based on visual styling selections made. I cannot recall what the default is. Can you confirm whether this is the case, and whether this addresses that particular concern of yours regarding plotting ambiguity?

I would like the application to automatically plot any functions defined like `f(x,y)` unless the user toggles visibility to be off. They should be standalone surfaces and used compositionally via the shared namespace. 


To make things more concrete around piecewise functions, I've added a tentative example in piecewise.py. Again, this is a rough sketch and totally open to tweaking. The non-pythonic `{}` to provide the piece arguments is inspired by desmos, though not truly faithful. The parser would need logic to format that into a proper python expression. Please let me know if this seems reasonable or difficult. 

Now, to potentially throw a wrench into the mix, one of the final things I want to make sure we consider before a mockup is the addition of recursive expressions. Please first describe to me how desmos handles these currently, and then review the example I added in recursion.py. Again, it's a rough sketch but should be illustrative of the functionality I'm interested in. That should also be sufficient to raise any design concerns up front. Let me know what you think. 



-------------------------------

Okay, go ahead and update the documentation with the areas we've ironed out on so far. 

If a case like `f(path)` returns an array shaped (N, 3) or (3,), that should be scatter-plotted by default. The type of plotting should be either dependent on the magic variables, function signature, or returned object if the first two are not valid plotting material. We we get returned something plot-able, we should try to do so. We shouldn't be plotting anything that returns scalars, lists, or 1D arrays. We also don't need to plot 2D arrays for now, though we could possibly choose to do so in the future and assume they lie in the z=0 plane. 

Regarding piecewise functions, the use of list syntax [] seems fine to me. If the return type is a list of functions, that's treated as piecewise. It would be a nice UX feature to automatically add N condition cells if it detects a piecewise definition with N elements. It should warn and not plot when the number of conditions is different from the number of pieces. 

Also, I was not imagining the `visible` fields as being actual text fields, but want to convey the state of the UI elements. To make that more clear, I went back and surrounded UI-native fields with tick quotes `` to indicate that they are not actually text. However! I think the serialization aspect is very appealing, and it would be nice to store or write or hold all of data selected in the front end to a portable yaml file that can be used to generate lightweight saves, diffs, support version control, and sharing. That would actually be a hugely useful feature. 

As to the issue of recurrence: I think we can actually circumvent the problems and treat recurrence relations directly as rules we apply to data cells. Please see recursion.py for a revised example. Rather than pretend they are functions and implement them as tables, we will just directly acknowledge and use them as rules that can be applied to tables in a vectorized manner. I threw in a naive implementation in the comment, but there are probably more efficient approaches. That should convey the core of the idea though, so let me know how much of a lift something like that would be given the current design. 

-------------------------------

Regarding confirmations:
1. Agree

2. Actually, I think we should make the initial condition setting explicit. Allow for multiple initial conditions to be added, of the form: 
```
initial_condition: path[0] = array(1, 0.1)
initial_condition: path[1] = array(2, 0.2)
```
For error checking, perhaps we can fill the array with nans besides the manually set initial condition, and if the recursion pulls nans (i.e. non-set initial conditions) we can detect and report it that way. If this is overly complicated for v1, we can just go with the previous assumption and implement this later. 

Additional thing to consider regarding recursion. We may want to access functions from the expression namespace to use in our recursion rules. For instance, we might want to do something like `recursion: path[n] = a + custom_func(path[n-1])`. Sounds like you were considering that possibility given (1), but wanted to double check. 


Regarding 3, can you re-review the desmos overview, our core architectural decisions, and some of the options available to us regarding UI/UX, GPU library options, and any other older options/decisions we considered in light of the more recent discussion? I want to surface any old items that may need reconsideration before sprinting toward a mockup. 


-------------------------------


One more question before picking a GPU/UI library: How crazy would it be to allow the user to pan around the viewer using the WASD keys, as well as space and shift to traverse the z axis? Which of the rendering tools we're considering would support this, if any?

For the inconsistencies:
3. I like the idea of supporting both # and """ and even regular "/' strings for comments. 
4. I prefer yaml. 
5. I don't have a strong preference here. I would default to whatever desmos does. If that isn't well documented, please use your best judgement for a reasonable baseline implementation. 
6. What happens if I define two functions like so:
```
z = x + y

z = x - y
```
I would expect this to plot both surfaces, where `z =` is sort of a generic syntax to say -> plot this as a surface. If z is passed into a function later, we probably do want that to pass in the z grid. Perhaps, in the parser, expressions defined as `z = ...` need to be assigned to some generic new expression variable name and plotted as a surface, so that we don't get namespace conflicts as I believe you were describing. 


7. This looks good to me. Only question/concern: what if a data cell relies on one of the equations? Does this play nice, or is that a chicken and egg problem? 

8. We want the data cells to also be moved around freely. Thus the data panel should also be implemented as a dependency graph. Does it make sense to put all of the data and equations on the same dependency graph, and have the separation purely be a UI and cell-type construct? Does that solve any of the boot order problems or make things more complicated?

9. Can we replace it with an underscore or something during the parsing and computation step? Since that variable is only computationally used in a for loop on run, it has a very transient scope. We don't want to cause namespace conflicts, but it is a useful/intuitive name to provide to the user. 

10. The user should have to click run each time they want to update data like that. We do not want data to update automatically from lambda changes, as that can cause chaotic effects, heavy lag, and the could trigger for each little edit a user makes. That would probably create an annoying experience for the user. 


-------------------------------

I've compacted the context, but all of our core design decisions are capture d in `design-docs`. Please refer to those for key details from our earlier conversations. I agree with your recommendations to use pygfx + wgpu-py + PyQt6, as well as the unified DAG and YAML. 

The last remaining thing that we haven't talked through in depth is user input. It should basically be all the standard Desmos input. Scroll controls zoom. Click and drag does an orbital rotation around the origin. 

We also want to use Desmos's axis settings. That is, we want to be able to manually set the axis bounds, recenter, and other basic quality of life features. Please review what desmos allows for in that regard. 

On the expression panel, clicking on a cell should select it and add an active cursor to the test box. Pressing enter should add a new cell inline and below the currently selected cell. The expression/data split and text panel vs GUI panel should be draggable. 

If there's any obvious user considerations I'm forgetting, please mention them. Document these and then provide me with a development plan -- what pieces should be built in what order and why. I'd also like to know how you would test each piece to ensure functionality. Since much of this requires visual verification, it would be useful to save off frames from the viewer as png files so that you can close the loop with development, testing, and validation. 
