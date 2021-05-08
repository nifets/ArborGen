# Filename: tree_gen.py
# Author:   Stefan Manolache
# This script is used to generate a semi-realistic tree model, together with an
# animation of its growth over its lifespan (including leaf growth and decay,
# flower blooming). 

#temp
ITERATIONS = 15

TIME_INTERVAL = 5 # how often to update simulation

import math
import random
import bpy
import numpy

from mathutils import Vector, Matrix, Euler

from typing import NamedTuple, List, Tuple

# Random stuff :)
#---------------------------------------------------------------------------------

# Represents a random 1D value based on an underlying normal distribution
class RandomValue(NamedTuple):
    mean: float
    stddev: float
        
    # get deterministic value
    def get(self):
        return numpy.random.normal(self.mean, self.stddev, None)
    
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

# Blender utility 
#---------------------------------------------------------------------------------
def createBone(rig, name, headLoc, tailLoc, parentName = None, 
               connected = False, inheritScale = 'NONE'):
    # select the armature
    bpy.context.view_layer.objects.active = rig
    # go into edit mode to add bones
    bpy.ops.object.mode_set(mode='EDIT', toggle=False)
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
    
    # go back into object mode
    bpy.ops.object.mode_set(mode='OBJECT')

# Create a vertex group that assigns full weights to the bone with the given name
def createVertexGroup(name, object):
    #assign vertex group weight
    group = object.vertex_groups.new(name = name)
    verts = []
    for v in object.data.vertices:
        verts.append(v.index)
    group.add(verts, 1.0, 'ADD')


# Tree part templates
# These are used in the growth logic as a blueprint for the production rule
#---------------------------------------------------------------------------------

# Production rule for a stem segment
class StemTemplate(NamedTuple):
    meshR: RandomMesh # mesh of the stem

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
    lengthRatioR: RV     # how much the stem should grow/shrink 
                         # in relation to the previous stem
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
            
        # reset shoot potential
        self.shootPotential = 0
            
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

        if self.shootPotential > 1 and not isInhibited:
            return self.type.shootGrowth()
        elif self.flowerPotential > 1 and self.age > 0:
            return self.type.flowerGrowth()
        return None
    
    # When the bud disappears, it has no influence over the child buds
    def done(self):
        self.dominance = 0.0001
    

class MeshPart:
    __slots__ = ('id', 'obj', 'boneName')
    def __init__(self, id, randomMesh, rig, parentId,
                 boneLength = 1, connected = False, inheritScale = 'NONE',
                 worldMatrix = Matrix.Identity(4), 
                 scaleMatrix = Matrix.Identity(4)):
        self.id = id
        
        #Create mesh
        self.obj = randomMesh.get()
        self.obj.matrix_world = worldMatrix @ scaleMatrix
        self.obj.name = "mesh_" + str(self.id)
        
        #Create bone
        self.boneName = "bone_" + str(self.id)
        parentName = "bone_" + str(parentId)
        headLoc = worldMatrix.to_translation()
        tailLoc = (worldMatrix @ Matrix.Translation((0, 0, boneLength))).to_translation()
        
        createBone(rig, self.boneName, headLoc, tailLoc, 
                   parentName, connected, inheritScale)
        
        #Create vertex group
        createVertexGroup(self.boneName, self.obj)
        
# A woody segment of the tree between 2 consecutive nodes. Features secondary growth (widening)   
class Stem:
    __slots__ = ('meshPart', 'length', 'id')
    
    def __init__(self, tree, stemT, parentMatrix, length, id, parentId): 
            self.length = length
            self.id = id
            scaleMatrix = Matrix.Diagonal(Vector((1.0,1.0,length,1.0)))
            self.meshPart = MeshPart(id, stemT.meshR, tree.rig, parentId,
                                     boneLength = length, connected = True,
                                     inheritScale = 'ALIGNED',
                                     worldMatrix = parentMatrix, 
                                     scaleMatrix = scaleMatrix)
                                     
            
    def update(self, secondaryGrowth):
        pass
        #do secondary growth
        
                                     
# Leaf part
class Leaf:
    __slots__ = ('meshPart', 'clorophyll')
    
    def __init__(self, tree, leafT, parentMatrix, id, parentId):
        size = leafT.sizeR.get()
        scaleMatrix = Matrix.Diagonal(Vector((size, size, size, 1.0)))
        self.meshPart = MeshPart(id, leafT.meshR, tree.rig, parentId,
                                 boneLength = size, connected = False,
                                 inheritScale = 'NONE',
                                 worldMatrix = parentMatrix, 
                                 scaleMatrix = scaleMatrix)
        self.clorophyll = 1.0
    
    # update leaf clorophyll 
    # return whether the leaf is still on the tree
    def update(self, loss):
        self.clorophyll -= loss
        if self.clorophyll < 0:
            self.fall()
            return True
        return False
        
    # make the leaf fall
    def fall(self):
        pass
        
# Flower/Fruit part
class Flower:
    __slots__ = ('flowerMeshPart',
                 'fruitMeshPart',
                 'potential',
                 'isFruit')
    def __init__(self, tree, flowerT, parentMatrix, flowerId, fruitId, parentId):
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
        
        
    def update(self, potential):
        self.potential += potential
        if not self.isFruit and self.potential > 1:
            self.makeFruit()
        if self.potential > 2: # isFruit = True
            self.fall()
            return True
        return False
                
    def makeFruit(self):
        self.isFruit = True
        #todo
    
    def fall(self):
        pass
    
            

    
        
            


            
    
    
# Main tree class
#---------------------------------------------------------------------------------  

class Tree:
    
    
    
    def __init__(self, budCollection, startBudT):
        self.budCollection = budCollection
        
        self.createRig()
        
        # age of the tree in years
        self.age = 0
        # current day in the year
        self.currDay = 1
        
        #id generator
        self.idGen = 1 
        
        # all tree leaves
        self.leaves = []
        self.fallenLeaves = []
        
        # all tree flowers
        self.flowers = []
        self.fallenFlowers = []
        
        # create root stem
        stemT = StemTemplate(RandomMesh(['default']))
        
        self.root = Stem(self, stemT, Matrix.Translation((0, 0, -1.0)), 1.0, self.getId(), 0)
        
        # all tree stems
        self.stems = [self.root]
        
        # create starting bud
        startBud = Bud(self, startBudT, Matrix.Identity(4), self.root)
        
        
        # all tree buds
        self.buds = [startBud]
    
    def getId(self):
        id = self.idGen
        self.idGen += 1
        return id
    
    def createRig(self):
        # the armature of the tree
        armature = bpy.data.armatures.new('TreeArmature')

        # create a rig and link it to the collection
        self.rig = bpy.data.objects.new('TreeRig', armature)
        bpy.context.scene.collection.objects.link(self.rig)
        
        createBone(self.rig, 'bone_0', (0.0, 0.0, -1.2), (0.0, 0.0, -1.0))

    
    def complete(self):
        # deselect all objects
        bpy.ops.object.select_all(action='DESELECT')

        #select all tree parts
        for stem in self.stems:
            stem.meshPart.obj.select_set(True)
        for leaf in self.leaves + self.fallenLeaves:
            leaf.meshPart.obj.select_set(True)
        for flower in self.flowers + self.fallenFlowers:
            flower.flowerMeshPart.obj.select_set(True)
            flower.fruitMeshPart.obj.select_set(True)
        
        #set branch to be active object
        bpy.context.view_layer.objects.active = self.root.meshPart.obj

        #join the object together
        bpy.ops.object.join()

        treemesh = bpy.context.view_layer.objects.active

        # parent the mesh to the armature
        treemesh.parent = self.rig
        treemesh.name = "TreeMesh"

        #add armature modifier
        treemesh.modifiers.new(name = 'Armature', type = 'ARMATURE')
        treemesh.modifiers['Armature'].object = self.rig
    
    
    # time - number of days to simulate growth for
    def grow(self, time = 1):
        for i in range(1, ITERATIONS + 1, 1):
            print("ITERATION " + str(i))
            # Buds that are spawned this iteration
            addedBuds = []
            
            # Update buds
            for bud in list(self.buds):
                growthRule = bud.update(0.6,0.1)
                
                # Grow into a shoot
                if type(growthRule) is ShootGrowthRule:
                    
                    oldParentMatrix = bud.worldMatrix
                    
                    stemT = growthRule.stemT
                    budT = growthRule.apiBudT
                    axilTs = growthRule.axilTs
                    
                    stemLength = bud.stem.length * growthRule.lengthRatioR.get()
                    
                    parentId = bud.stem.id
                    
                    # create stem
                    stem = Stem(self, stemT, oldParentMatrix, 
                                stemLength, self.getId(), parentId)
                    self.stems.append(stem)
                    
                    
                    parentMatrix = oldParentMatrix @ Matrix.Translation((0,0,stemLength))
                     
                    # renew apical bud
                    bud.renew(self, budT, parentMatrix, stem)
                    
                    # create axillary buds and leaves
                    for (axiBudT, leafT) in axilTs:
                        axiBud = Bud(tree, axiBudT, parentMatrix, stem, bud)
                        
                        leafWorldMatrix = axiBud.worldMatrix
                        leaf = Leaf(tree, leafT, leafWorldMatrix, 
                                    self.getId(), parentId)
                        addedBuds.append(axiBud)
                        self.leaves.append(leaf)
                    
                # Grow into a flower
                elif type(growthRule) is FlowerGrowthRule:
                    parentMatrix = bud.worldMatrix
                    
                    flowerT = growthRule.flowerT
                    
                    parentId = bud.stem.id
                    
                    # create flower
                    flower = Flower(self, flowerT, parentMatrix, 
                                    self.getId(), self.getId(), parentId)
                    self.flowers.append(flower)
                    
                    # remove bud
                    self.buds.remove(bud)
                    bud.done()
                    
            self.buds.extend(addedBuds)        
             
            # Update stems
            self.root.update(1.0) # enough to do secondary growth on root stem
            
            # Update leaves
            for leaf in list(self.leaves):
                hasFallen = leaf.update(0.0)
                if hasFallen:
                    self.leaves.remove(leaf)
                    self.fallenLeaves.append(leaf)
                
            # Update flowers
            for flower in list(self.flowers):
                hasFallen = flower.update(1.0)     
                if hasFallen:
                    self.flowers.remove(flower)
                    self.fallenFlowers.append(flower)
            


#example
        
stemMeshR = RandomMesh(['stem'])

stemT = StemTemplate(RandomMesh(['stem']))

leafT = LeafTemplate(RandomMesh(['leaf']), RV(0.2, 0.01))

flowerT = FlowerTemplate(RM(['flower']), RM(['fruit']), RV(0.2, 0.01))

startBudT = BudTemplate(index = 0, dominance = 1.0,
                        brcAngleR = RV(0.0,20.0),
                        divAngleR = RV(0.0,60.0),
                        rollAngleR = RV(0.0,180.0),
                        )
budT = BudTemplate(index = 0, dominance = 1.0,
                    brcAngleR = RV(0.0,3.0),
                    divAngleR = RV(0.0,1.0),
                    rollAngleR = RV(180.0,30.0)
                    )
                    
budT1 = BudTemplate(index = 0, dominance = 2.0,
                    brcAngleR = RV(60.0,2.0),
                    divAngleR = RV(180.0,30.0),
                    rollAngleR = RV(0.0,1.0)
                    )
                    
shootRule = ShootGrowthRule(stemT, RV(0.6,0.01), budT, [(budT1, leafT), (budT1, leafT)])
flowerRule = FlowerGrowthRule(flowerT)
budCollection = BudCollection()


                    
budCollection.add(0, [shootRule], [1.0], flowerRule)

    
tree = Tree(budCollection, startBudT)
tree.grow()
tree.complete()