# Filename: tree_gen.py
# Author:   Stefan Manolache
# This script is used to generate a semi-realistic tree model, together with an
# animation of its growth over its lifespan (including leaf growth and decay,
# flower blooming). 


TIME_INTERVAL = 20 # how often to update simulation

import math
import random
import bpy
import numpy
import time

from mathutils import Vector, Matrix, Euler

from typing import NamedTuple, List, Tuple

# Time
#---------------------------------------------------------------------------------
startTime = time.time()
def clock():
    print(time.time() - startTime)


# Random stuff :)
#---------------------------------------------------------------------------------

# Represents a random uniformly distributed variable
class RandomValue(NamedTuple):
    mean: float
    error: float
        
    # get deterministic value
    def get(self):
        x =  numpy.random.uniform(self.mean - self.error, 
                                  self.mean + self.error, None)
        return x
    
RV = RandomValue

# Represents a mesh which can vary in appearance
class RandomMesh:
    def __init__(self, meshNames):
        # all possible meshes 
        self.meshes = []
        for name in meshNames:
            self.meshes.append(bpy.data.objects[name])
            
    # get deterministic mesh
    def get(self):
        # choose a mesh uniformly at random
        initMesh = random.choice(self.meshes)
        
        mesh = initMesh.copy()
        # important, so that mesh data is not linked to the original
        mesh.data = initMesh.data.copy()
        bpy.context.collection.objects.link(mesh)
        return mesh

RM = RandomMesh


# Bone stuff
#---------------------------------------------------------------------------------

# Doing ops inside the script has a lot of overhead, so instead of
# creating the bone when the function is called, we add the task to a queue
# and we create all the bones at the end of the run.

editBonesQ = []
keyframesQ = []

# add edit bone to queue
def createBone(id, headLoc, tailLoc, parentId = None, 
               connected = False, inheritScale = 'NONE', inheritRotation = True):
                   
    name = "bone_" + str(id)
    
    if parentId == None:
        parentName = None
    else:
        parentName = "bone_" + str(parentId)
        
    editBonesQ.append((name, headLoc, tailLoc, 
                      parentName, connected, inheritScale, inheritRotation))
    return name
                      
# add the edit bones to the rig
def flushEditBonesQ(rig):
    # select the armature
    bpy.context.view_layer.objects.active = rig
    # go into edit mode to add bones
    bpy.ops.object.mode_set(mode='EDIT', toggle=False)
    
    for task in editBonesQ:
        (name, headLoc, tailLoc, parentName, connected, 
         inheritScale, inheritRotation) = task
        makeEditBone(rig, name, headLoc, tailLoc, 
                      parentName, connected, inheritScale, inheritRotation)
                      
    # go back into object mode
    bpy.ops.object.mode_set(mode='OBJECT')
        
# add an individual edit bone to the rig
def makeEditBone(rig, name, headLoc, tailLoc, parentName = None, 
               connected = False, inheritScale = 'NONE', inheritRotation = True):
                   
    
    # need to be in edit mode to add edit bones
    assert bpy.context.object.mode == 'EDIT'
    
    # add a bone to the armature
    bone = rig.data.edit_bones.new(name)
    bone.head = headLoc
    bone.tail = tailLoc
    
    # set parent if applicable
    if parentName is not None:
        parent = rig.data.edit_bones[parentName]
        bone.parent = parent
    
    # set properties
    bone.use_connect = connected
    bone.inherit_scale = inheritScale
    bone.use_inherit_rotation = inheritRotation
    
    
def addKeyframe(boneName, type, transform, frame, relative = False):
    keyframesQ.append((boneName, type, transform, frame, relative))
    
def flushKeyframesQ(rig):
    for task in keyframesQ:
        (boneName, type, transform, frame, relative) = task
        makeKeyframe(rig, boneName, type, transform, frame, relative)
    
    
# create the actual keyframe
def makeKeyframe(rig, boneName, type, transform, frame, relative):
    bone = rig.pose.bones[boneName]
    if type == 'scale':
        if not relative:
            bone.scale = (0.0,0.0,0.0)
        bone.scale = (Vector(bone.scale) + Vector(transform)).to_tuple()
        bone.keyframe_insert('scale', frame = frame)
    elif type == 'location':
        if not relative:
            bone.location = (0.0,0.0,0.0)
        bone.location = (Vector(bone.location) + Vector(transform)).to_tuple()
        bone.keyframe_insert('location', frame = frame)
        
    



# Create a vertex group that assigns full weights to the bone with the given name
def createVertexGroup(name, object):
    #assign vertex group weight
    group = object.vertex_groups.new(name = name)
    verts = []
    for v in object.data.vertices:
        verts.append(v.index)
    group.add(verts, 1.0, 'ADD')
    
    
    

# Growth Function 
#---------------------------------------------------------------------------------

class GrowthFunction:
    def __init__(self, fcurveDay, fcurveYear, stddev):
        self.fcurveDay = fcurveDay
        self.fcurveYear = fcurveYear
        self.stddev = stddev
        
    def evaluate(self, year, startDay, endDay):
        yearModifier = self.fcurveYear.evaluate(year)
        mean = self.fcurveDay.evaluate(endDay) - self.fcurveDay.evaluate(startDay)
        
        '''print("end day and start dayv value")
        print(self.fcurveDay.evaluate(endDay))
        print(self.fcurveDay.evaluate(startDay))'''
        
        
        if (endDay < startDay): # if end day is in the next year
            mean += self.fcurveDay.evaluate(365)
            
        '''print("mean and year mod")
        print(mean)
        print(yearModifier)'''
        
        return RV(mean * yearModifier, self.stddev)
        
        
# Tree part templates
# These are used in the growth logic as a blueprint for the production rule
#---------------------------------------------------------------------------------

# Production rule for a stem segment
class StemTemplate(NamedTuple):
    meshR: RandomMesh # mesh of the stem
    lengthRatioR: RV       # length of the stem

class LeafTemplate(NamedTuple):
    meshR: RandomMesh # mesh of the leaf
    sizeR: RV         # size of the leaf

# This encodes both a flower and its resulting fruit
class FlowerTemplate(NamedTuple):
    flowerMeshR: RandomMesh # mesh of the flower
    fruitMeshR: RandomMesh  # mesh of the fruit
    sizeR: RV               # size of the flower/fruit


# Production rule for a bud 
# This does not directly include what the bud could grow into
# Instead, that is encoded in the index variable
# see Diagram 1 for angle explanation
class BudTemplate(NamedTuple):
    index: int       # bud type index
    dominance: float # how much apical dominance the bud exhibits
    brcAngleR: RV    # branching angle
    divAngleR: RV    # divergence angle
    rollAngleR: RV   # roll angle
    
    
# Bud Growth Logic  
#---------------------------------------------------------------------------------    
    

    
# Production Rules

class ShootGrowthRule(NamedTuple):
    stemT: StemTemplate 
    apiBudT: BudTemplate # apical bud
    axilTs: List[Tuple[BudTemplate, LeafTemplate]] # axillary buds and leaves
    
class FlowerGrowthRule(NamedTuple):
    flowerT: FlowerTemplate
         
    
# Describes what a specific bud type can grow into
# This class is tightly-coupled with BudCollection 
# Instances should only be created by using BudCollection.add
# (not sure how to enforce this -- my python expertise -> 0
class BudType:
    def __init__(self, shootRules, shootWeights, flowerRule):
        self.shootRules = shootRules
        self.shootWeights = shootWeights # list of probabilities of shoot rules
        self.flowerRule = flowerRule
    
    # Apply one of the shoot growth rules (based on the probability distribution)
    # Return a stem template and a list of axillary bud templates
    def shootGrowth(self):
        rule = random.choices(self.shootRules, self.shootWeights)
        return rule[0]
    
    def flowerGrowth(self):
        return flowerRule
        
    
# Stores all possible bud types of a tree
# There should be at least one bud type
# The bud with index 0 is the starting bud
class BudCollection:
    def __init__(self):
        # dict storing all bud types
        self.buds = {}
    
    # add bud type to the collection
    def add(self, index, shootRules, shootWeights, flowerRule):
        budType = BudType(shootRules, shootWeights, flowerRule)
        self.buds[index] = budType
    
    # get the bud type at given index
    def get(self, index):
        return self.buds[index]
    
    
# Tree parts
#---------------------------------------------------------------------------------  

# Represents the growing part of the tree, which can either develop into a stem 
# (with new nodes and leaves attached) or into a flower.
class Bud:
    __slots__ = (
        'type',           # what kind of bud this is
        'worldMatrix',    # world transform of the bud
        'shootPotential', # how close the bud is to growing into a shoot
        'flowerPotential',# how close the bud is to growing into a flower
        'stem',           # the stem this bud is attached to 
        'apicalBud',      # the parent bud of this bud
        'age',             # how many shoots the bud produced
        'dominance'
    )
    
    def __init__(self, tree, budT, parentMatrix, parentStem, apicalBud = None):

        self.age = -1

        # set the apical bud
        self.apicalBud = apicalBud
            
        # set the flower potential
        self.flowerPotential = 0
            
        self.shootPotential = 1
            
        # apply the template and set the world transformation of the mesh
        self.renew(tree, budT, parentMatrix, parentStem)
        
    # Transform the bud after it has sprouted into a shoot
    def renew(self, tree, budT, parentMatrix, parentStem):
        self.age += 1
        
        # set the type of the bud
        self.type = budCollection.get(budT.index)
                    
        # set dominance
        self.dominance = budT.dominance
                    
        # set the parent stem
        self.stem = parentStem
            
        # update shoot potential
        self.shootPotential -= 1
        
        # set the flower potential
        self.flowerPotential = 0
            
        # calculate the world transform of the bud from the budT angles
        divAngle = math.radians(budT.divAngleR.get())
        brcAngle = math.radians(budT.brcAngleR.get())
        rollAngle = math.radians(budT.rollAngleR.get())
        eul = Euler((0.0, brcAngle, divAngle), 'XYZ').to_matrix().to_4x4()
        roll = Matrix.Rotation(rollAngle, 4, 'Z')
            
        self.worldMatrix = parentMatrix @ eul @ roll
        
    
    # Update the bud with the given potentials.
    def update(self, shootPotential, flowerPotential):
        self.shootPotential += shootPotential
        self.flowerPotential += flowerPotential
        # how much is the growth of this bud inhibited by the axilarry bud
        isInhibited = False
        if self.age is 0 and self.apicalBud is not None: #if axilarry bud
            distance = (self.apicalBud.worldMatrix.to_translation() - self.worldMatrix.to_translation()).length
            if distance / self.apicalBud.dominance < 1:
                isInhibited = True
        '''print(self.shootPotential)
        print(self.flowerPotential)
        print(self.age)'''
        '''if self.flowerPotential > 1 and self.age > 0:
            print("flower")
            return self.type.flowerGrowth()
        elif self.shootPotential > 1:
            if not isInhibited:
                return self.type.shootGrowth()
            else:
                self.shootPotential -= 1'''
        if self.shootPotential > 1:
            if not isInhibited:
                return self.type.shootGrowth()
            else:
                self.shootPotential -= 1
        if self.flowerPotential > 1 and self.age > 0:
            return self.type.flowerGrowth()

                
        
        return None
    
    # When the bud disappears, it has no influence over the child buds
    def done(self):
        self.dominance = 0.0001
    

class MeshPart:
    __slots__ = ('id', 'obj', 'boneName')
    def __init__(self, id, randomMesh, rig, parentId,
                 boneLength = 1, connected = False, 
                 inheritScale = 'NONE', inheritRotation = True,
                 worldMatrix = Matrix.Identity(4), 
                 scaleMatrix = Matrix.Identity(4)):
                     
        self.id = id
        
        #Create mesh
        self.obj = randomMesh.get()
        self.obj.matrix_world = worldMatrix @ scaleMatrix
        self.obj.name = "mesh_" + str(self.id)
        
        #Create bone

        headLoc = worldMatrix.to_translation()
        tailLoc = (worldMatrix @ Matrix.Translation((0, 0, boneLength))).to_translation()
        
        self.boneName = createBone(self.id, headLoc, tailLoc, 
                                   parentId, connected, inheritScale, inheritRotation)
        
        #Create vertex group
        createVertexGroup(self.boneName, self.obj)
        
    def addKeyframe(self, type, transform, frame, relative = False):# add a keyframe
        addKeyframe(self.boneName, type, transform, frame, relative)
        
        
# A woody segment of the tree between 2 consecutive nodes. Features secondary growth (widening)   
class Stem:
    __slots__ = ('meshPart', 'length', 'id', 'secondaryGrowthGain', 'thick')
    
    
    def __init__(self, tree, stemT, parentMatrix, parentLength, 
                 id, parentId, startFrame, endFrame, parentThick):          
        
        self.length = parentLength * stemT.lengthRatioR.get()
        self.id = id
        self.secondaryGrowthGain = 0.0
        scaleMatrix = Matrix.Diagonal(Vector((1.0,1.0,self.length,1.0)))
        self.meshPart = MeshPart(id, stemT.meshR, tree.rig, parentId,
                                 boneLength = self.length, connected = True,
                                 inheritScale = 'NONE',
                                 worldMatrix = parentMatrix, 
                                 scaleMatrix = scaleMatrix)
            
        #animate sprouting (primary growth)
        self.thick = parentThick * 0.9
        self.meshPart.addKeyframe('scale',(0.0,0.0,0.0), startFrame)
        self.meshPart.addKeyframe('scale',(self.thick,0.7,self.thick), endFrame + 20.0*self.length, relative = True)
        self.meshPart.addKeyframe('scale',(0.0,0.3,0.0), endFrame + 40.0*self.length, relative = True)
            
                                     
    def update(self, secondaryGrowth, frame):
        self.secondaryGrowthGain += secondaryGrowth*0.05 * self.thick
        if (self.secondaryGrowthGain > 0.2):
            gain = self.secondaryGrowthGain
            self.meshPart.addKeyframe('scale',(gain,0.0,gain), frame, relative = True)
            self.secondaryGrowthGain = 0.0
        #do secondary growth
        
                                     
# Leaf part
class Leaf:
    __slots__ = ('meshPart', 'clorophyll', 'colour')
    
    def __init__(self, tree, leafT, parentMatrix, 
                 id, parentId, startFrame, endFrame):
        size = leafT.sizeR.get()
        scaleMatrix = Matrix.Diagonal(Vector((size, size, size, 1.0)))
        self.meshPart = MeshPart(id, leafT.meshR, tree.rig, parentId,
                                 boneLength = size, connected = False,
                                 inheritScale = 'NONE', inheritRotation = False,
                                 worldMatrix = parentMatrix, 
                                 scaleMatrix = scaleMatrix)
        self.clorophyll = 1.0
        
        #animate sprouting
        self.meshPart.addKeyframe('scale',(0.0,0.0,0.0), startFrame)
        self.meshPart.addKeyframe('scale',(0.5,0.5,0.5), endFrame + 20.0*size)
        self.meshPart.addKeyframe('scale',(1.0,1.0,1.0), endFrame + 60.0*size)
        
        # animate colour
        '''self.colour = self.meshPart.obj.active_material.diffuse_color
        self.meshPart.obj.active_material.keyframe_insert('diffuse_color', startFrame)'''
    
    # update leaf clorophyll 
    # return whether the leaf is still on the tree
    def update(self, loss, frame):
        self.clorophyll -= loss
        '''self.meshPart.obj.active_material.diffuse_color[1] = self.clorophyll * self.colour[1] 
        self.meshPart.obj.active_material.diffuse_color[0] = (1-self.clorophyll) * self.colour[0]
        self.meshPart.obj.active_material.keyframe_insert('diffuse_color', frame)'''
        if self.clorophyll < 0:
            self.fall(frame)
            return True
        return False
        
    # make the leaf fall
    def fall(self,frame):
        rframe = frame + int(numpy.random.uniform(0,10, None))
        self.meshPart.addKeyframe('location',(0.0,0.0,0.0), rframe, relative = True)
        self.meshPart.addKeyframe('location',(0.0,0.1,0.0), rframe+1, relative = True)
        self.meshPart.addKeyframe('location',(0.0,0.15,-0.3), rframe + 10, relative = True)
        self.meshPart.addKeyframe('location',(0.0,0.1,-0.1), rframe + 31, relative = True)
        self.meshPart.addKeyframe('scale',(1.0,1.0,1.0), rframe +30)
        self.meshPart.addKeyframe('scale',(0.0,0.0,0.0), rframe +31)
        
# Flower/Fruit part
class Flower:
    __slots__ = ('flowerMeshPart',
                 'fruitMeshPart',
                 'potential',
                 'isFruit')
    def __init__(self, tree, flowerT, parentMatrix, flowerId, fruitId, parentId, startFrame, endFrame):
        size = flowerT.sizeR.get()
        scaleMatrix = Matrix.Diagonal(Vector((size, size, size, 1.0)))
        self.flowerMeshPart = MeshPart(flowerId, flowerT.flowerMeshR,
                                 tree.rig, parentId,
                                 boneLength = size, connected = False,
                                 inheritScale = 'NONE',
                                 worldMatrix = parentMatrix, 
                                 scaleMatrix = scaleMatrix)
        self.fruitMeshPart = MeshPart(fruitId, flowerT.fruitMeshR,
                                 tree.rig, parentId,
                                 boneLength = size, connected = False,
                                 inheritScale = 'NONE',
                                 worldMatrix = parentMatrix, 
                                 scaleMatrix = scaleMatrix)
        self.potential = 0
        self.isFruit = False
        
        #animate sprouting
        self.flowerMeshPart.addKeyframe('scale',(0.0,0.0,0.0), startFrame)
        self.flowerMeshPart.addKeyframe('scale',(1.0,1.0,1.0), startFrame + 10)
        self.fruitMeshPart.addKeyframe('scale',(0.0,0.0,0.0), startFrame)
        
        
    def update(self, potential, frame):
        self.potential += potential
        if not self.isFruit and self.potential > 1:
            rframe = frame + int(numpy.random.uniform(0,6, None))
            self.flowerMeshPart.addKeyframe('location',(0.0,0.0,0.0), rframe, relative = True)
            self.flowerMeshPart.addKeyframe('location',(0.0,-1.0,0.0), rframe + 10, relative = True)
            self.flowerMeshPart.addKeyframe('scale',(1.0,1.0,1.0), frame + 9)
            self.flowerMeshPart.addKeyframe('scale',(0.0,0.0,0.0), frame + 10)
            self.makeFruit(frame)
        if self.potential > 2: # isFruit = True
            self.fall(frame)
            return True
        return False
                
    def makeFruit(self,frame):
        self.isFruit = True
        self.fruitMeshPart.addKeyframe('scale',(0.0,0.0,0.0), frame)
        self.fruitMeshPart.addKeyframe('scale',(1.0,1.0,1.0), frame + 15)
        #todo
    
    def fall(self, frame):
        rframe = frame + int(numpy.random.uniform(0,10, None))
        self.fruitMeshPart.addKeyframe('location',(0.0,0.0,0.0), rframe, relative = True)
        self.fruitMeshPart.addKeyframe('location',(0.0,-2.5,0.0), rframe + 20, relative = True)
        self.fruitMeshPart.addKeyframe('location',(0.0,-7.0,0.0), rframe + 40, relative = True)
        self.fruitMeshPart.addKeyframe('scale',(1.0,1.0,1.0), rframe +40)
        self.fruitMeshPart.addKeyframe('scale',(0.0,0.0,0.0), rframe +41)
    
            

    
        
            


            
    
    
# Main tree class
#---------------------------------------------------------------------------------  

class Tree:
    
    
    
    def __init__(self, budCollection, startBudT, primaryGrowthF, secondaryGrowthF,
                 bloomingF, fruitGrowthF, leafDecayF):
        self.budCollection = budCollection
        
        self.createRig()
        
        # age of the tree in years
        self.year = 0
        # current day in the year
        self.day = 1
        
        #id generator
        self.idGen = 1 
        
        # all tree leaves
        self.leaves = []
        self.fallenLeaves = []
        
        # all tree flowers
        self.flowers = []
        self.fallenFlowers = []
        
        # create root stem
        stemT = StemTemplate(RandomMesh(['root']), RV(1.0,0.01))
        
        self.root = Stem(self, stemT, Matrix.Translation((0, 0, -1.0)), 1.0, 
                         self.getId(), 0, 0, 0, 1.0)
        
        # all tree stems
        self.stems = [self.root]
        
        # create starting bud
        startBud = Bud(self, startBudT, Matrix.Identity(4), self.root)
        
        
        # all tree buds
        self.buds = [startBud]
        
        # set growth functions
        self.primaryGrowthF = primaryGrowthF
        self.secondaryGrowthF = secondaryGrowthF
        self.bloomingF = bloomingF
        self.fruitGrowthF = fruitGrowthF
        self.leafDecayF = leafDecayF
        
    
    def getId(self):
        id = self.idGen
        self.idGen += 1
        return id
    
    def createRig(self):
        # the armature of the tree
        armature = bpy.data.armatures.new('TreeArmature')
        armature.display_type = 'WIRE'
        # create a rig and link it to the collection
        self.rig = bpy.data.objects.new('TreeRig', armature)
        bpy.context.scene.collection.objects.link(self.rig)
        
        createBone(0, (0.0, 0.0, -1.2), (0.0, 0.0, -1.0))

    
    def complete(self):
        # create edit bones
        flushEditBonesQ(self.rig)

        # create keyframes
        flushKeyframesQ(self.rig)

        # deselect all objects
        bpy.ops.object.select_all(action='DESELECT')

        clock()

        #select all tree parts
        for stem in self.stems:
            stem.meshPart.obj.select_set(True)
        for leaf in self.leaves + self.fallenLeaves:
            leaf.meshPart.obj.select_set(True)
        for flower in self.flowers + self.fallenFlowers:
            flower.flowerMeshPart.obj.select_set(True)
            flower.fruitMeshPart.obj.select_set(True)
        
        clock()
        
        #set branch to be active object
        bpy.context.view_layer.objects.active = self.root.meshPart.obj

        #join the object together
        print("joining...")
        bpy.ops.object.join()

        treemesh = bpy.context.view_layer.objects.active

        # parent the mesh to the armature
        treemesh.parent = self.rig
        treemesh.name = "TreeMesh"

        #add armature modifier
        treemesh.modifiers.new(name = 'Armature', type = 'ARMATURE')
        treemesh.modifiers['Armature'].object = self.rig
    
    
    # time - number of days to simulate growth for
    def grow(self, time = 1, leafGrowth = 1.0, flowerGrowth = 1.0):
        for i in range(0, time, TIME_INTERVAL):
            # update tree age
            startDay = self.day
            year = self.year
            
            startFrame = self.year * 365 + self.day
            
            self.day += TIME_INTERVAL # TIME_INTERVAL < 365
            
            
            if self.day > 365:
                self.day -= 365
                self.year += 1
                print("Current age: " + str(self.year))
            print("Day: " + str(self.day))
            
            endDay = self.day
            
            
            endFrame = self.year * 365 + self.day
            
            
            addedBuds = []
            
            
            
            # Update buds
            primaryGrowthR = self.primaryGrowthF.evaluate(year, startDay, endDay)
            bloomingR = self.bloomingF.evaluate(year, startDay, endDay)
            for bud in list(self.buds):
                growthRule = bud.update(primaryGrowthR.get(),bloomingR.get())
                
                # Grow into a shoot
                if type(growthRule) is ShootGrowthRule:
                    
                    oldParentMatrix = bud.worldMatrix
                    
                    stemT = growthRule.stemT
                    budT = growthRule.apiBudT
                    axilTs = growthRule.axilTs
                    
                    parentId = bud.stem.id
                    
                    # create stem
                    stem = Stem(self, stemT, oldParentMatrix, bud.stem.length,
                                self.getId(), parentId, startFrame, endFrame,
                                bud.stem.thick)
                    self.stems.append(stem)
                    
                    stemLength = stem.length
                    
                    parentMatrix = oldParentMatrix @ Matrix.Translation((0,0,stemLength))
                     
                    # renew apical bud
                    bud.renew(self, budT, parentMatrix, stem)
                    
                    parentId = stem.id
                    
                    # create axillary buds and leaves
                    for (axiBudT, leafT) in axilTs:
                        axiBud = Bud(tree, axiBudT, parentMatrix, stem, bud)
                        addedBuds.append(axiBud)
                        
                        if numpy.random.uniform(0.0, 1.0, None) <= leafGrowth:
                            
                            translation = axiBud.worldMatrix.to_translation()
                            
                            z = parentMatrix.to_euler('ZXY').z
                            y = math.radians(RV(90.0,20.0).get())
                            x = math.radians(RV(0.0,10.0).get())
                            rotation = Euler((x,y,z),'YZX').to_matrix().to_4x4()
                            leafWorldMatrix = Matrix.Translation(translation) @ rotation
                            leaf = Leaf(tree, leafT, leafWorldMatrix,
                                        self.getId(), parentId, startFrame, endFrame)
                            
                            self.leaves.append(leaf)
                    
                # Grow into a flower
                elif type(growthRule) is FlowerGrowthRule:
                    parentMatrix = bud.worldMatrix
                    
                    flowerT = growthRule.flowerT
                    
                    parentId = bud.stem.id
                    
                    # create flower
                    if numpy.random.uniform(0.0, 1.0, None) <= flowerGrowth:
                        print("flower")
                        parentMatrix = bud.worldMatrix
                        
                        translation = parentMatrix.to_translation()
                        z = math.radians(RV(0.0,90.0).get())
                        rotation = Euler((0, 0, z), 'YZX').to_matrix().to_4x4()
                        flowerWorldMatrix = Matrix.Translation(translation) @ rotation 
                        
                        flower = Flower(self, flowerT, flowerWorldMatrix, self.getId(), 
                                        self.getId(), parentId, startFrame, endFrame)
                        self.flowers.append(flower)
                    
                        # remove bud
                        self.buds.remove(bud)
                        bud.done()
                    else:
                        bud.flowerPotential -= 1
                    
            self.buds.extend(addedBuds)        
             
            # Update stems
            secondaryGrowth = self.secondaryGrowthF.evaluate(year, startDay, endDay).get()
            for stem in list(self.stems):
                stem.update(secondaryGrowth, endFrame) 
            
            # Update leaves
            leafDecayR = self.leafDecayF.evaluate(year, startDay, endDay)
            for leaf in list(self.leaves):
                hasFallen = leaf.update(leafDecayR.get(), endFrame)
                if hasFallen:
                    self.leaves.remove(leaf)
                    self.fallenLeaves.append(leaf)
                
            # Update flowers
            fruitGrowthR = self.fruitGrowthF.evaluate(year, startDay, endDay)
            for flower in list(self.flowers):
                hasFallen = flower.update(fruitGrowthR.get(), endFrame)     
                if hasFallen:
                    self.flowers.remove(flower)
                    self.fallenFlowers.append(flower)
            


#Oak
        
trunkT = StemTemplate(RM(['OakTrunk']),RV(0.8,0.1))
mainT = StemTemplate(RM(['Stem']),RV(0.84,0.1))
branchT = StemTemplate(RM(['Stem']), RV(0.84,0.1))
twigT = StemTemplate(RM(['Stem']), RV(0.84,0.1))

leafT = LeafTemplate(RandomMesh(['OakLeaf0','OakLeaf1']), RV(0.3,0.01))
flowerT = FlowerTemplate(RM(['OakFlower']), RM(['Acorn']), RV(0.3, 0.03))


startBudT = BudTemplate(index = 0, dominance = 8.0,
                        brcAngleR = RV(0.0,1.0),
                        divAngleR = RV(0.0,60.0),
                        rollAngleR = RV(0.0,270.0),
                        )

budTtrunk = BudTemplate(index = 1, dominance = 2.0,
                        brcAngleR = RV(0.0,15.0),
                        divAngleR = RV(0.0,180.0),
                        rollAngleR = RV(137.0,30.0)
                        )

budTmainApi = BudTemplate(index = 2, dominance = 2.0,
                        brcAngleR = RV(10.0,10.0),
                        divAngleR = RV(0.0,180.0),
                        rollAngleR = RV(137.0,30.0)
                        )
budTmain = BudTemplate(index = 2, dominance = 1.0,
                        brcAngleR = RV(50.0,10.0),
                        divAngleR = RV(90.0,180.0),
                        rollAngleR = RV(137.0,30.0)
                        )
                        
budTbranchApi = BudTemplate(index = 3, dominance = 0.2,
                        brcAngleR = RV(0.0,10.0),
                        divAngleR = RV(80.0,180.0),
                        rollAngleR = RV(137.0,20.0),
                        )
budTbranch = BudTemplate(index = 3, dominance = 0.1,
                        brcAngleR = RV(40,10.0),
                        divAngleR = RV(80.0,180.0),
                        rollAngleR = RV(137.0,20.0),
                        )
                        
budTtwigApi = BudTemplate(index = 4, dominance = 0.1,
                        brcAngleR = RV(4.0,20.0),
                        divAngleR = RV(180.0,180.0),
                        rollAngleR = RV(137.0,20.0),
                        )
budTtwig = BudTemplate(index = 4, dominance = 0.1,
                        brcAngleR = RV(40.0,20.0),
                        divAngleR = RV(180.0,180.0),
                        rollAngleR = RV(137.0,20.0),
                        )
                     
rule00 = ShootGrowthRule(trunkT, budTtrunk, 
        [(budTmain, leafT),(budTmain, leafT)])
rule01 = ShootGrowthRule(trunkT, budTtrunk, 
        [(budTmain, leafT)])
rule02 = ShootGrowthRule(trunkT, budTtrunk, 
        [])
        
rule10 = ShootGrowthRule(mainT, budTtrunk, 
        [(budTmain, leafT),(budTmain, leafT)])
rule11 = ShootGrowthRule(mainT, budTtrunk, 
        [(budTmain, leafT)])
rule12 = ShootGrowthRule(mainT, budTtrunk, 
        [])
rule13 = ShootGrowthRule(mainT, budTmainApi, 
        [(budTmain, leafT)])

rule20 = ShootGrowthRule(branchT, budTmainApi, 
        [(budTbranch, leafT),(budTbranch, leafT)])
rule21 = ShootGrowthRule(branchT, budTmainApi, 
        [(budTbranch, leafT)])
rule22 = ShootGrowthRule(branchT, budTmainApi, 
        [])
rule23 = ShootGrowthRule(branchT, budTbranchApi, 
        [])
        
        
rule30 = ShootGrowthRule(branchT, budTbranchApi, 
        [(budTtwig, leafT),(budTtwig, leafT)])
rule31 = ShootGrowthRule(branchT, budTbranchApi, 
        [(budTtwig, leafT)])
rule32 = ShootGrowthRule(branchT, budTtwigApi, 
        [(budTtwig, leafT)])
        
rule40 = ShootGrowthRule(twigT, budTtwigApi, 
        [(budTtwig, leafT),(budTtwig, leafT)])
rule41 = ShootGrowthRule(twigT, budTtwigApi, 
        [(budTtwig, leafT)])
rule42 = ShootGrowthRule(twigT, budTtwigApi, 
        [])
                
        
flowerRule = FlowerGrowthRule(flowerT)

budCollection = BudCollection()


                    
budCollection.add(0, [rule00, rule01, rule02], [0.8,0.1, 0.1], flowerRule)
budCollection.add(1, [rule10,rule11, rule12, rule13], [0.1,0.3,0.1,0.3], flowerRule)
budCollection.add(2, [rule20,rule21, rule22, rule23], [0.1,0.5,0.1,0.3], flowerRule)
budCollection.add(3, [rule30, rule31, rule32], [0.07,0.5,0.43], flowerRule)
budCollection.add(4, [rule40, rule41,rule42], [0.15, 0.84, 0.01], flowerRule)


    
fcurves = bpy.data.objects['OakGrowthFunctions'].animation_data.action.fcurves

primaryGrowthF = GrowthFunction(fcurves.find('["primaryGrowthDay"]'),
                                fcurves.find('["primaryGrowthYear"]'), 0.01)



secondaryGrowthF = GrowthFunction(fcurves.find('["secondaryGrowthDay"]'),
                                  fcurves.find('["secondaryGrowthYear"]'), 0.1)

bloomingF = GrowthFunction(fcurves.find('["bloomingDay"]'),
                           fcurves.find('["bloomingYear"]'), 0.1)

fruitGrowthF = GrowthFunction(fcurves.find('["fruitGrowthDay"]'),
                              fcurves.find('["fruitGrowthYear"]'), 0.05)

leafDecayF = GrowthFunction(fcurves.find('["leafDecayDay"]'),
                            fcurves.find('["leafDecayYear"]'), 0.01)

    
tree = Tree(budCollection, startBudT, 
            primaryGrowthF, secondaryGrowthF, bloomingF, fruitGrowthF, leafDecayF)
    
tree.grow(4380, 1.0, 1.0)
tree.grow(1410, 1.0, 0.4)

     
print("growing done")
clock()
tree.complete()

clock()